import logging
import math
import re

from reportlab.lib.utils import ImageReader
import reportlab.graphics.shapes as shapes
import reportlab.graphics.renderPDF as renderPDF

import pdfgen_utils as pu

logger = pu.getLogger()

class PngImage(shapes.Shape):
    """ PngImage 
        This Shape subclass allows for adding PNG images to a PDF without
        using the Python Image Library
    """ 
    x = 0
    y = 0
    width = 0
    height = 0
    path = None
    clipRect = None   
 
    def __init__(self, x, y, width, height, path, clipRect=None, **kw):
        """ if clipRect == None, then the entire image will be drawn at (x,y) -> (x+width, y+height)
            if clipRect = (cx0, cy0, cx1, cy1), all coordinates are in the same space as (x,y), but with (x,y) as origin
                then
                iwidth = image.width, iheight = image.height
                ix0 = (cx0-x)*image.width/width
                ix1 = (cx1-x)*image.width/width
                iy0 = (cy0-y)*image.height/height
                iy1 = (cy1-y)*image.height/height 
                the subset of the image, given by (ix0, iy0, ix1, iy0) will be drawn at (x,y)->(x+cx1-cx0, y+cy1-cy0)
        """
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.path = path

        if clipRect != None:
            self.origWidth = width
            self.origHeight = height
            self.width = clipRect[2] - clipRect[0]
            self.height = clipRect[3] - clipRect[1]
            self.clipRect = clipRect           
 
    def copy(self):
        new = self.__class__(self.x, self.y, self.width, self.height, self.path, self.clipRect)
        new.setProperties(self.getProperties())
        return new

    def getBounds(self):
        if self.clipRect == None:
            return (self.x, self.y, self.x + self.width, self.y + self.height)
        else:
            return (self.x, self.y, self.x + self.clipRect[2] - self.clipRect[0], self.y + self.clipRect[3] - self.clipRect[1])

    def _drawTimeCallback(self, node, canvas, renderer):
        if not isinstance(renderer, renderPDF._PDFRenderer):
            logger.error("PngImage only supports PDFRenderer")
            return

        image = PngImageReader(self.path)
        if self.clipRect != None:
            (imageWidth, imageHeight) = image.getSize()
            imageClipRect = (int(math.floor(self.clipRect[0] * imageWidth / self.origWidth)), 
                             int(math.floor(self.clipRect[1] * imageHeight / self.origHeight)),
                             int(math.ceil(self.clipRect[2] * imageWidth / self.origWidth)),
                             int(math.ceil(self.clipRect[3] * imageHeight / self.origHeight)))
            
            image.setClipRect(imageClipRect)

        canvas.drawImage(image, self.x, self.y, width=self.width, height=self.height)

class PngImageReader(ImageReader):
    _format = None
    _isRemote = False
    _clipRect = None

    # PNG data
    _pixelComponentString = None

    def __init__(self, fileName):
        """ fileName is either a local file or a remote file (http)
            clipRect is either None, indicating no clipping, or a 4-tuple of left, top, right, bottom
        """
        # check if the file is remote, if so, download it to a temporary file and reset fileName
        self._isRemote = _getIsRemote(fileName)
        if self._isRemote:
            fileName, self._format = _getRemoteFile(fileName) 
        else: 
            self._format = _getFormat(fileName)
        
        if self._format != 'png':
            raise IllegalFormat(fileName, 'PNG')        


        self._dataA = None

        import png
        self._pngReader = png.Reader(filename=fileName)
        self._pngReaderInfo = png.Reader(filename=fileName)
        self._pngReaderInfo.preamble()
        self.mode = 'RGB'
        self._width = self._pngReaderInfo.width
        self._height = self._pngReaderInfo.height  
        
    def setClipRect(self, clipRect):
        if clipRect != None:
            if clipRect[2] <= clipRect[0]:
                raise InvalidClipRect(clipRect)
            if clipRect[3] <= clipRect[1]:
                raise InvalidClipRect(clipRect)
            if clipRect[2] > self._width or clipRect[0] < 0:
                raise InvalidClipRect(clipRect)
            if clipRect[3] > self._height or clipRect[1] < 0:
                raise InvalidClipRect(clipRect) 

            self._clipRect = clipRect

            clipRectWidth = self._clipRect[2] - self._clipRect[0]
            clipRectHeight = self._clipRect[3] - self._clipRect[1]
            self._width = clipRectWidth
            self._height = clipRectHeight

    def getRGBData(self):
        if self._pixelComponentString is None:
            # rows is an iterator that returns an Array for each row, 
            #   each pixel is represented by 3 successive values, R, G, B
            (dataWidth, dataHeight, rows, metaData) = self._pngReader.asDirect() 
          
            dataRect = (0, 0, dataWidth, dataHeight) if self._clipRect == None else self._clipRect
            # adjust for 3 bytes per pixel
            outputRect = (dataRect[0] * 3, dataRect[1], dataRect[2] * 3, dataRect[3]) 

            # we need to return a string of bytes: RGBRGBRGBRGBRGB...
            pixelComponentArray = []
            for (rowIdx, row) in enumerate(rows):
                if rowIdx >= outputRect[1] and rowIdx < outputRect[3]:
                    for byteIdx in range(outputRect[0], outputRect[2]):
                        pixelComponentArray.append(chr(row[byteIdx]))

            self._pixelComponentString = ''.join(pixelComponentArray)    
        return self._pixelComponentString

    def getTransparent(self):
        # need to override -- or not, not sure when this is used
        raise NotImplementedError

class JpgImageReader(ImageReader):
    _format = None
    _isRemote = False

    def __init__(self, fileName,ident=None):
        # check if the file is remote, if so, download it to a temporary file and reset fileName
        self._isRemote = _getIsRemote(fileName)
        if self._isRemote:
            fileName, self._format = _getRemoteFile(fileName) 
        else: 
            self._format = _getFormat(fileName)
        
        if self._format != 'jpg':
            raise IllegalFormat(fileName, 'JPG')        


        ImageReader.__init__(self, fileName, ident)

    def getRGBData(self):
        return ImageReader.getRGBData(self)

    def getTransparent(self):
        return ImageReader.getTransparent(self)


def _getFormat(fileName):
    m = re.search('.([^.]+)$', fileName)
    if m is None:
        return None

    # since the regex matched and there are required
    # characters in the group capture, there must be a index-1 group
    fileSuffix = m.group(1)
    fileSuffix = fileSuffix.lower()
    
    if fileSuffix == "jpg" or fileSuffix == "jpeg":
        return "jpg"
    elif fileSuffix == "png":
        return "png"
    
    return None

def _getIsRemote(fileName):
    m = re.search('^(http|https)', fileName)
    if m is None:
        return False
    return True    

class IllegalFormat(Exception):
    def __init__(self, fileName, format):
        self.fileName = fileName
        self.format = format
    
    def __str__(self):
        return "%s is not a %s file" % (self.fileName, self.format)

class CannotAccessRemoteImage(Exception):
    def __init__(self, path, status):
        self.path = path
        self.status = status
    def __str__(self):
        return "Cannot access %s status=%s" % (self.path, self.status) 

class InvalidClipRect(Exception):
    def __init__(self, clipRect):
        self.clipRect = clipRect
    
    def __str__(self):
        return "%s is an invalid clipRect" % str(self.clipRect)

def _getRemoteFile(path):
    ''' uses httplib2 to retrieve @path
        returns tuple: the local path to the downloaded file, the format
        raises exception on any failure
    '''
    import httplib2
    http = httplib2.Http(timeout=60, disable_ssl_certificate_validation=True)
    (response, content) = http.request(path)
    if response.status < 200 or response.status >= 400:
        raise CannotAccessRemoteImage(path, response.status)
    
    format = ''
    content_type = response.get('content-type')
    if content_type == 'image/png':
        format = 'png'
    elif content_type =='image/jpeg':
        format = 'jpg'
 
    import tempfile
    localFile = tempfile.NamedTemporaryFile(delete=False)
    localFile.write(content)
    localFile.close()
    return localFile.name, format

if __name__ == '__main__':
    import unittest

    class ImageTest(unittest.TestCase):
        def test_ImageReader_size(self):
            imageReaderJPG = JpgImageReader("svg_image_test.jpg")
            self.assertEquals(imageReaderJPG._width, 399)
            self.assertEquals(imageReaderJPG._height, 470)
            
            imageReaderPNG = PngImageReader("svg_image_test.png")
            self.assertEquals(imageReaderPNG._width, 250)
            self.assertEquals(imageReaderPNG._height, 183)

            imageReaderPNGClipped = PngImageReader("svg_image_test.png")
            imageReaderPNGClipped.setClipRect((10, 10, 50, 60))
            self.assertEquals(imageReaderPNGClipped._width, 40)
            self.assertEquals(imageReaderPNGClipped._height, 50)

        def test_illegal_image_format(self):
            with self.assertRaises(IllegalFormat):
                imageReader = PngImageReader("test.tiff")
        
        def test_cannot_access_remote_image(self):
            with self.assertRaises(CannotAccessRemoteImage):
                imageReader = PngImageReader("http://www.splunk.com/imageThatDoesntExist.png")

        def test_invalid_clip_rect(self):
            with self.assertRaises(InvalidClipRect):
                imageReader = PngImageReader("svg_image_test.png")
                imageReader.setClipRect((10, 10, 5, 5))       
 
            with self.assertRaises(InvalidClipRect):
                imageReader = PngImageReader("svg_image_test.png")
                imageReader.setClipRect((0, -4, 30, 40))           
 
            with self.assertRaises(InvalidClipRect):
                imageReader = PngImageReader("svg_image_test.png")
                imageReader.setClipRect((0, 0, 500, 40)) 

        def test_clipping(self):
            clipRect = (10, 20, 100, 110)
            imageReader = PngImageReader("svg_image_test.png")
            imageReader.setClipRect(clipRect)
            imageData = imageReader.getRGBData()          
            imageDataLen = len(imageData)
            self.assertEquals(imageDataLen, (clipRect[2] - clipRect[0]) * (clipRect[3] - clipRect[1]) * 3)  
 
    unittest.main()

