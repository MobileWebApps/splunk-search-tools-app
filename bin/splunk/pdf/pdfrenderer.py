#import time
import logging
import copy
import re
import math
import xml.sax.saxutils as su

import reportlab
import reportlab.pdfgen
import reportlab.pdfgen.canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, CondPageBreak, Preformatted, TableStyle, Flowable, Spacer, FrameBreak
from reportlab.platypus.flowables import UseUpSpace
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.colors import Color
import reportlab.lib.colors as colors
from reportlab.pdfbase import pdfmetrics
from reportlab.graphics import renderPDF
import reportlab.lib.enums

from reportlab.lib import pagesizes 
import pdfgen_svg
import pdfgen_utils as pu
from font_manager import FontManager

logger = pu.getLogger()

PAPERSIZES = {
    "letter":
        {
            'reportLabPaperSize': pagesizes.LETTER,
            'ellipsizedTitleCount': 45,
            'logoTransformSize': 0.33
        },
    "letter-landscape":
        {
            'reportLabPaperSize': pagesizes.landscape(pagesizes.LETTER),
            'ellipsizedTitleCount': 80,
            'logoTransformSize': 0.33
        },
    "legal":
        {
            'reportLabPaperSize': pagesizes.LEGAL,
            'ellipsizedTitleCount': 45,
            'logoTransformSize': 0.33
        },
    "legal-landscape":
        {
            'reportLabPaperSize': pagesizes.landscape(pagesizes.LEGAL),
            'ellipsizedTitleCount': 100,
            'logoTransformSize': 0.33
        },
    "eleven-seventeen":
        {
            'reportLabPaperSize': pagesizes.ELEVENSEVENTEEN,
            'ellipsizedTitleCount': 70,
            'logoTransformSize': 0.33
        },
    "eleven-seventeen-landscape":
        {
            'reportLabPaperSize': pagesizes.landscape(pagesizes.ELEVENSEVENTEEN),
            'ellipsizedTitleCount': 150,
            'logoTransformSize': 0.33
        },
    "tabloid":
        {
            'reportLabPaperSize': pagesizes.ELEVENSEVENTEEN,
            'ellipsizedTitleCount': 70,
            'logoTransformSize': 0.33
        },
    "ledger":
        {
            'reportLabPaperSize': pagesizes.landscape(pagesizes.ELEVENSEVENTEEN),
            'ellipsizedTitleCount': 150,
            'logoTransformSize': 0.33
        },
    "a5":
        {
            'reportLabPaperSize': pagesizes.A5,
            'ellipsizedTitleCount': 30,
            'logoTransformSize': 0.20
        },
    "a5-landscape":
        {
            'reportLabPaperSize': pagesizes.landscape(pagesizes.A5),
            'ellipsizedTitleCount': 45,
            'logoTransformSize': 0.33
        },
    "a4":
        {
            'reportLabPaperSize': pagesizes.A4,
            'ellipsizedTitleCount': 45,
            'logoTransformSize': 0.33
        },
    "a4-landscape":
        {
            'reportLabPaperSize': pagesizes.landscape(pagesizes.A4),
            'ellipsizedTitleCount': 70,
            'logoTransformSize': 0.33
        },
    "a3":
        {
            'reportLabPaperSize': pagesizes.A3,
            'ellipsizedTitleCount': 75,
            'logoTransformSize': 0.33
        },
    "a3-landscape":
        {
            'reportLabPaperSize': pagesizes.landscape(pagesizes.A3),
            'ellipsizedTitleCount': 125,
            'logoTransformSize': 0.33
        },
    "a2":
        {
            'reportLabPaperSize': pagesizes.A2,
            'ellipsizedTitleCount': 125,
            'logoTransformSize': 0.33
        },
    "a2-landscape":
        {
            'reportLabPaperSize': pagesizes.landscape(pagesizes.A2),
            'ellipsizedTitleCount': 225,
            'logoTransformSize': 0.33
        },
    "a1":
        {
            'reportLabPaperSize': pagesizes.A1,
            'ellipsizedTitleCount': 125,
            'logoTransformSize': 0.33
        },
    "a1-landscape":
        {
            'reportLabPaperSize': pagesizes.landscape(pagesizes.A1),
            'ellipsizedTitleCount': 225,
            'logoTransformSize': 0.33
        },
    "a0":
        {
            'reportLabPaperSize': pagesizes.A0,
            'ellipsizedTitleCount': 125,
            'logoTransformSize': 0.33
        },
    "a0-landscape":
        {
            'reportLabPaperSize': pagesizes.landscape(pagesizes.A0),
            'ellipsizedTitleCount': 225,
            'logoTransformSize': 0.33
        }
}   

TABLE_FONT_NAME = "Helvetica"
TABLE_FONT_SIZE = 6
STYLES = getSampleStyleSheet()

class PDFRenderer(object):

    ONE_INCH = 1.0 * inch
    MIN_HEIGHT_TABLE_AND_CHART = 4 * inch

    _fontManager = None

    outputFile = None
    reportLabPaperSize = (0, 0)
    _includeSplunkLogo = True
    _title = ""
    _story = []
    _runningAsScript = False

    _style = STYLES["Normal"]
    CENTER_STYLE = copy.deepcopy(STYLES['Normal'])
    TITLE_STYLE = copy.deepcopy(STYLES["Normal"])
    BULLET_STYLE = STYLES["Bullet"]
    _bulletStyle = STYLES["Bullet"]
    _tableTitleStyle = STYLES["Title"]
    _listTitleStyle = STYLES["Bullet"]
    _hardWrapStyle = copy.deepcopy(STYLES["Normal"])
    _hardWrapStyle.wordWrap = "CJK"
    _TABLE_COL_LEFT_PADDING = 2
    _TABLE_COL_RIGHT_PADDING = 2    
    _MARGINS = [inch, inch, inch, inch]

    def __init__(self, title, outputFile, paperSize, timestamp="", includeSplunkLogo=None, cidFontList=None):
        """ outputFile can either be a filename or a file-like object """
        self.outputFile = outputFile
        self.paperSize = paperSize
        self.reportLabPaperSize = PAPERSIZES[self.paperSize]['reportLabPaperSize']
        self.logoTransformSize = PAPERSIZES[self.paperSize]['logoTransformSize']
        self._log("outputFile: " + str(self.outputFile))
        self._log("reportLabPaperSize: " + str(self.reportLabPaperSize))
        self._title = title
        self._timestamp = timestamp
        if includeSplunkLogo != None:
            self._includeSplunkLogo = includeSplunkLogo
        logger.debug("pdf-init pdfrenderer include-splunk-logo=%s" % self._includeSplunkLogo)

        self._fontManager = FontManager(cidFontList=cidFontList)

        self.TITLE_STYLE.fontSize = 14
        self.TITLE_STYLE.leading = 16
        self.CENTER_STYLE.alignment=reportlab.lib.enums.TA_CENTER

        # TODO: need a better way to determine max cell height
        #       225 ~= margins + footer height + a few lines for header row
        self.maxTableCellHeight = self.reportLabPaperSize[1] - 225
        return

    def conditionalPageBreak(self):
        self._story.append(CondPageBreak(self.MIN_HEIGHT_TABLE_AND_CHART))

    def spaceBetween(self, space = 0.5 * inch):
        self._story.append(EnsureSpaceBetween(space))

    def renderText(self, text, style = None, escapeText = True):
        if style is None:
            style = self._style

        if escapeText:
            readyText = su.escape(text)
        else:
            readyText = text

        logger.debug("renderText readyText='%s'" % readyText)
        self._story.append(Paragraph(self._fontManager.encodeTextForParagraph(readyText), style))

    def renderBulletText(self, text, bullet = '-', style = None):
        if style is None:
            style = self._bulletStyle
        self._story.append(Paragraph(self._fontManager.encodeTextForParagraph(su.escape(text)), style, bulletText = bullet))

    def renderHtml(self, text):
        if text is None:
            return

        def multiple_replacer(*key_values):
            replace_dict = dict(key_values)
            replacement_function = lambda match: replace_dict[match.group(0)]
            pattern = re.compile("|".join([re.escape(k) for k, v in key_values]), re.M)
            return lambda string: pattern.sub(replacement_function, string)

        def multiple_replace(string, *key_values):
            return multiple_replacer(*key_values)(string)        

        # reportlab supports a set of text manipulation tags
        #  transform those HTML tags that aren't supported into reportlab 
        #  supported tags    
        lineBreakingTagReplacements = (
            u"<li>", u"<li><br/>"), (
            u"<h1>", u"<h1><font size='24'><br/><br/>"), (
            u"</h1>", u"</font><br/></h1>"), (
            u"<h2>", u"<h2><font size='20'><br/><br/>"), (
            u"</h2>", u"</font><br/></h2>"), (
            u"<h3>", u"<h3><font size='18'><br/><br/>"), (
            u"</h3>", u"</font><br/></h3>"), (
            u"<h4>", u"<h4><font size='14'><br/>"), (
            u"</h4>", u"</font><br/></h4>"), (
            u"<h5>", u"<h5><font size='12'><br/>"), (
            u"</h5>", u"</font><br/></h5>"), (
            u"<h6>", u"<h6><br/>"), (
            u"</h6>", u"<br/></h6>"), (
            u"<h7>", u"<h7><br/>"), (
            u"</h7>", u"<br/></h7>"), (
            u"<h8>", u"<h8><br/>"), (
            u"</h8>", u"<br/></h8>"), (
            u"<h9>", u"<h9><br/>"), (
            u"</h9>", u"<br/></h9>"), (
            u"<h10>", u"<h10><br/>"), (
            u"</h10>", u"<br/></h10>"), (
            u"<br>", u"<br/>"), (
            u"<p>", u"<p><br/>")

        repText = multiple_replace(text, *lineBreakingTagReplacements)
       
        # need to remove some elements
        #  any elements that make references to external things -- don't want reportlab to try to resolve links
        #  reportlab doesn't like the title attribute
        removeElements = [
            '(<img[^>]*>)', '(</img>)',
            '(title="[^"]*")',
            '(<a[^>]*>)', '(</a>)'
            ]
            
        repText = re.sub('|'.join(removeElements), '', repText)
        logger.debug("renderHtml text='%s' repText='%s'" % (text, repText))

        self.renderText(repText, escapeText=False)    



    def renderTextNoFormatting(self, text):
        self._story.append(TableText(text, fontManager=self._fontManager))

    def renderListItem(self, text, sequencerNum = None, style = None):
        if style is None:
            style = self._listTitleStyle
        if sequencerNum != None:
            text = "<seq id="+str(sequencerNum)+"/>" + text
        self._story.append(Paragraph(self._fontManager.encodeTextForParagraph(su.escape(text)), style))

    def renderTable(self, data, title = None, headerRow = None, columnWidths = [], columnHardWraps = [], columnVAlignments = [], displayLineNumbers = False):
        """ data should be a 2-D list of embedded lists e.g. [[a,b],[c,d],[e,f]]
            if headerRow is specified, then that row will be repeated at the top of each page if the table spans multiple pages,
            columnWidths ([int]) specifies the width of each column, if a column is not specified it will be sized automatically,
            columnHardWraps ([bool]) specifies whether or not to hard wrap a column, if a column is not specified it will be wrapped softly
            columnVAlignments (['TOP','MIDDLE','BOTTOM']) specifies vertical alignment of cells in a column, if not specified will be aligned at BOTTOM
            displayLineNumbers (bool) specifies whether or not to show line numbers
        """

        # handle title and header
        if title != None:
            self.renderText(title, style = self._tableTitleStyle)
        if headerRow != None:
            data.insert(0, headerRow)
            logger.debug("renderTable> headerRow: " + str(headerRow))

        # handle row numbers
        if displayLineNumbers:
            for index, row in enumerate(data):
                if index == 0 and headerRow != None:
                    row.insert(0, "")
                else:
                    rowNumber = index
                    if headerRow == None:
                        rowNumber = rowNumber + 1
                    row.insert(0, str(rowNumber))        

        numDataCols = 0

        # iterate over the data in order to wrap each cell in a Paragraph flowable with a style
        numberCells = [] # an array of tuples identifying cells that are numbers
        cellWidthsByCol = []
        styledData = []
        for rowIdx, row in enumerate(data):
            styledRow = []

            for cellNum, cell in enumerate(row):
                # set the style based on columnHardWraps[cellNum]
                style = self._style
                if len(columnHardWraps) > cellNum:
                    if columnHardWraps[cellNum]:
                        style = self._hardWrapStyle

                cellFlowable = None
                if "##__SPARKLINE__##" in str(cell):
                    # build sparkline and insert into row
                    cellFlowable = Sparkline(str(cell))
                    styledRow.append(cellFlowable)
                else:
                    cellFlowable = TableText(str(cell), fontManager=self._fontManager, maxCellHeight=self.maxTableCellHeight)
                    styledRow.append(cellFlowable)
                    if cellFlowable.isNumeric():
                        numberCells.append((cellNum, rowIdx))

                # build up matrix of cell widths by column 
                if rowIdx == 0:
                    cellWidthsByCol.append([])
                cellWidthsByCol[cellNum].append(cellFlowable.width)

            numDataCols = len(styledRow)
            styledData.append(styledRow)

        columnWidths = self.determineColumnWidths(cellWidthsByCol, tableWidth=self.reportLabPaperSize[0] - self._MARGINS[0] - self._MARGINS[2], columnPadding=self._TABLE_COL_LEFT_PADDING + self._TABLE_COL_RIGHT_PADDING)

        # create the necessary table style commands to handle vertical alignment setting
        tableStyleCommands = []
        if columnVAlignments is not None:
            for i, valign in enumerate(columnVAlignments):
                tableStyleCommands.append(('VALIGN', (i, 0), (i, -1), valign))

        for numberCell in numberCells:
            tableStyleCommands.append(('ALIGN', numberCell, numberCell, 'RIGHT')) 

        # line to the right of all columns
        tableStyleCommands.append(('LINEAFTER', (0, 0), (-2, -1), 0.25, colors.lightgrey))

        firstDataRow = 0
        if headerRow != None:
            tableStyleCommands.append(('LINEBELOW', (0, 0), (-1, 0), 1, colors.black))
            firstDataRow = 1

        # lines to the bottom and to the right of each cell
        tableStyleCommands.append(('LINEBELOW', (0, firstDataRow), (-1, -2), 0.25, colors.lightgrey))

        # tighten up the columns
        tableStyleCommands.append(('LEFTPADDING', (0, 0), (-1, -1), self._TABLE_COL_LEFT_PADDING))
        tableStyleCommands.append(('RIGHTPADDING', (0, 0), (-1, -1), self._TABLE_COL_RIGHT_PADDING))

        # create the Table flowable and insert into story
        table = Table(styledData, repeatRows=(headerRow != None), colWidths=columnWidths)
        table.setStyle(TableStyle(tableStyleCommands))
        self._story.append(table)

    def determineColumnWidths(self, cellWidthsByCol, tableWidth, columnPadding):
        columnSizer = ColumnSizer(cellWidthsByCol, tableWidth, columnPadding)
        return columnSizer.getWidths()

    def renderSvgString(self, svgString, title = None):
        svgImageFlowable = pdfgen_svg.getSvgImageFromString(svgString, self._fontManager)
        if svgImageFlowable is None:
            self._log("renderSvg> svgImageFlowable for " + svgString + " is invalid")
        else:
            if title != None:
                self.renderText(title, style = self._tableTitleStyle)
            self._story.append(svgImageFlowable)

    def save(self):
#        self._log("starting save", logLevel='info')
        doc = PDFGenDocTemplate(self.outputFile, pagesize=self.reportLabPaperSize)
        doc.setTitle(self._title)
        doc.splunkPaperSize = self.paperSize
        doc.setTimestamp(self._timestamp)
        doc.setFontManager(self._fontManager)
        if self._includeSplunkLogo:
            doc.setLogoSvgString(_splunkLogoSvg.replace("***logoTransformSize***", str(self.logoTransformSize)))
        self._log("Doc pageSize: " + str(getattr(doc, "pagesize")))

        for flowable in self._story:
            flowable.hAlign = 'CENTER'
#        self._log("before doc.build", logLevel='info')
        doc.build(self._story, onFirstPage=_footer, onLaterPages=_footer)
#        self._log("after doc.build", logLevel='info')
#        if len(wrapTimes) > 1: 
#            self._log("wrap time stats; min=%s, max=%s, agg=%s, avg=%s, num=%s" % _getStats(wrapTimes), logLevel='info') 
#        if len(stringWidthTimes) > 1:
#            self._log("width time stats; min=%s, max=%s, agg=%s, avg=%s, num=%s" % _getStats(stringWidthTimes), logLevel='info')         
#        self._log("font manager cache length=%s" % len(self._fontManager._textWidthCache), logLevel='info')
#        if len(drawTimes) > 1:
#            self._log("draw time stats; min=%s, max=%s, agg=%s, avg=%s, num=%s" % _getStats(drawTimes), logLevel='info')         

    def _log(self, msg, logLevel='debug'):
        if self._runningAsScript:
            print logLevel + " : " + msg
            return

        if logLevel=='debug':
            logger.debug(msg)
        elif logLevel=='info':
            logger.info(msg)
        elif logLevel=='warning':
            logger.warning(msg)
        elif logLevel=='error':
            logger.error(msg)


#def _getStats(array):
#    minVal = None
#    maxVal = None
#    aggVal = 0
#    avgVal = None
#    numVals = len(array)
#    if numVals > 0:
#        for val in array:
#            aggVal = aggVal + val
#            if minVal == None or minVal > val:
#                minVal = val
#            if maxVal == None or maxVal < val:
#                maxVal = val
#        avgVal = aggVal / numVals
#    return (minVal, maxVal, aggVal, avgVal, numVals) 

#wrapTimes = []
#stringWidthTimes = []
#drawTimes = []

#
# TableText
# This Flowable subclass wraps HARD at width boundaries
#
class TableText(Flowable):
    """ TableText
        I couldn't get ReportLab's Paragraph flowables to appropriately wrap text strings
        without whitespace. The entire point of this class is to allow the breaking
        of text in the middle of words when necessary. This entire class can use a good
        look for optimization and cleanup
    """

    _text = ""
    _prewrapLines = []
    _lines = []
    height = 0
    width = 0
    _fontSize = 0
    _lineHeight = 0
    _fontManager = None
    _maxCellHeight = 0
    _isNumber = None

    def __init__(self, text, fontManager = None, fontSize = TABLE_FONT_SIZE, maxCellHeight = 100):
        assert(text != None)
        assert(fontManager != None)        
        
        #self._showBoundary = True
        utfText = text
        if isinstance(text, str):
            utfText = text.decode('utf-8')

        # setup private variables
        self._fontManager = fontManager
        self._fontSize = fontSize
        self._lineHeight = self._fontSize + 2
        self._maxCellHeight = maxCellHeight

        # store the text data in its individual lines
        self._prewrapLines = utfText.splitlines()
        self._maxWidth = None
        self.width = self.getMaxWidth()

    def isNumeric(self):
        if self._isNumber != None:
            return self._isNumber

        self._isNumber = True
        for line in self._prewrapLines:
            if not isNumber(line):
                self._isNumber = False
                break

        return self._isNumber

    def getMaxWidth(self):
        if self._maxWidth != None:
            return self._maxWidth

        self._maxWidth = 0

        for prewrapLine in self._prewrapLines:
            self._maxWidth = max(self._maxWidth, self._fontManager.textWidth(prewrapLine, self._fontSize))

        return self._maxWidth 

    def wrap(self, availWidth, availHeight):
        # self._wrap returns the width required for the text
        #start = time.time()
        self.width = self._wrap(availWidth)
        #finish = time.time()
        #wrapTimes.append(finish - start)
        self.height = self._lineHeight * len(self._lines)
        #logger.debug("TableText::wrap> availWidth: " + str(availWidth) + ", availHeight: " + str(availHeight) + ", width: " + str(self.width) + ", height: " + str(self.height))
        return self.width, self.height

    def draw(self):
        """ draw each line """
        #start = time.time()
        self.canv.saveState()
        for i, line in enumerate(self._lines):
            textObj = self.canv.beginText(x = 0, y = self.height - (i + 1) * self._lineHeight)
            self._fontManager.addTextAndFontToTextObject(textObj, line, self._fontSize)
            self.canv.drawText(textObj)
        self.canv.restoreState()
        #finish = time.time()
        #drawTimes.append(finish - start)

    def _wrap(self, availWidth):
        """ fills the self._lines array with the actual text to output in self.draw()
            returns minWidthRequired

            this is a VERY VERY dumb word wrapping algorithm
            we first split the text based on line breaks, then for each original line:
                1) if the entire line fits in the availWidth, then output the line
                2) split the line into individual words, fill the output line with words that fit
                3) when we reach the point that the next word will overflow the availWidth, then
                    a) if the word will fit on the next line, put it on the next line, otherwise
                    b) split the word so that we fill the current line, then deal with the rest of the word on the next line
        """

        self._lines = []
        minWidthRequired = 0

        if len(self._prewrapLines) == 0:
            return minWidthRequired

        spaceWidth = self._fontManager.textWidth(" ", self._fontSize)

        tempLines = self._prewrapLines
        currentTempLine = 0
        #logger.debug("TableText::_wrap> availWidth: " + str(availWidth) + ", tempLines: " + str(tempLines))
        for currentTempLine, tempLine in enumerate(tempLines):
            tempLineWidth = self._fontManager.textWidth(tempLine, self._fontSize)
            #logger.debug("TableText::_wrap> tempLine: " + tempLine + ", tempLineWidth: " + str(tempLineWidth))

            if tempLineWidth <= availWidth:
                # easy case: the entire line fits within availWidth

                #logger.debug("TableText::_wrap> tempLineWidth <= availWidth")
                self._lines.append(tempLine)
                minWidthRequired = tempLineWidth
            else:
                # the line needs to be wrapped in order to fit in availWidth
                # break the line into tokens, each token is a word or number or a punctuation character

                tempWords = re.split("(\W)", tempLine)
                totalLinesHeight = len(self._lines) * self._lineHeight
                while len(tempWords) > 0 and totalLinesHeight < self._maxCellHeight:
                    #logger.debug("TableText::_wrap> starting new line. Words left: " + str(tempWords))
                    currentLineWords = []
                    remainingWidth = availWidth

                    fillingCurrentLine = True
                    # TODO: remove any leading spaces

                    while fillingCurrentLine:
                        tempWord = tempWords.pop(0)

                        # reportlab doesn't handle \t character. replace with space
                        if tempWord == '\t':
                            tempWord = ' '

                        #start = time.time()
                        tempWordWidth = self._fontManager.textWidth(tempWord, self._fontSize)
                        #finish = time.time()
                        #stringWidthTimes.append(finish-start)


                        #addSpace = False
                        #logger.debug("TableText::_wrap> word: " + tempWord + ", wordWidth: " + str(tempWordWidth) + ", remainingWidth: " + str(remainingWidth))
                        if len(currentLineWords) > 0:
                            tempWordWidth = tempWordWidth + spaceWidth
                            #addSpace = True

                        if tempWordWidth <= remainingWidth:
                            # temp word can fit in the remaining space
                            #logger.debug("TableText::_wrap> can fit within remaining space")

                            #if addSpace:
                            #	currentLineWords.append(" ")
                            currentLineWords.append(tempWord)
                            remainingWidth = remainingWidth - tempWordWidth
                        elif tempWordWidth <= availWidth:
                            # temp word cannot fit in the remaining space, but can fit on a new line
                            #logger.debug("TableText::_wrap> cannot fit within remaining space, but can fit on next line")

                            tempWords.insert(0, tempWord)
                            remainingWidth = 0
                            fillingCurrentLine = False
                        else:
                            # temp word cannot fit in the remaining space, nor can it fit on a new line
                            # hard-break a segment off the word that will fit in the remaining space
                            #logger.debug("TableText::_wrap> cannot fit within remaining space, and cannot fit on next line")

                            #if addSpace:
                            #	remainingWidth = remainingWidth - spaceWidth
                            firstSegment, restOfWord = self._wrapWord(tempWord, remainingWidth, wordWidth = tempWordWidth)
                            #logger.debug("TableText::_wrap> broke word " + tempWord + " into: " + firstSegment + " and " + restOfWord)
                            tempWords.insert(0, restOfWord)
                            #if addSpace:
                            #	currentLineWords.append(" ")
                            currentLineWords.append(firstSegment)
                            fillingCurrentLine = False

                        if len(tempWords) == 0:
                            # we're done filling the current line, given that there are no more words
                            fillingCurrentLine = False

                    currentLine = "".join(currentLineWords)
                    self._lines.append(currentLine)
                    totalLinesHeight = len(self._lines) * self._lineHeight
                    minWidthRequired = max(minWidthRequired, availWidth - remainingWidth)

            # check to see if we need to truncate the cell's contents
            if (len(self._lines) * self._lineHeight) >= self._maxCellHeight:
                break

        if (currentTempLine + 1) < len(tempLines):
            # we truncated
            percentageShown = (100.0 * float(currentTempLine) / float(len(tempLines)))
            logger.info("TableText::_wrap> truncated cell contents. %s%% shown." % percentageShown)
            # TODO: this needs to be internationalized
            self._lines.append("... Truncated. %s%% shown." % percentageShown)

        logger.debug("TableText::_wrap> minWidthRequired: " + str(minWidthRequired) + ", self._lines: " + str(self._lines))
        return minWidthRequired

    def _wrapWord(self, word, availWidth, wordWidth = 0):
        """ returns a tuple: firstSegment, restOfWord where firstSegment will fit in the availWidth """
        wordLen = len(word)

        if wordWidth == 0:
            wordWidth = self._fontManager.textWidth(word)

        # TODO: for a starting point, assume that we can break proportionally
        #breakIndex = int(float(wordLen) * float(availWidth) / float(wordWidth))

        breakIndex = 0
        segmentWidth = 0
        nextCharWidth = self._fontManager.textWidth(word[breakIndex], self._fontSize)

        while (segmentWidth + nextCharWidth) < availWidth:
            breakIndex = breakIndex + 1
            if breakIndex >= wordLen:
                # TODO: better exception handling
                raise ValueError("Cannot establish break in word: " + str(word))
            segmentWidth = segmentWidth + nextCharWidth
            nextCharWidth = self._fontManager.textWidth(word[breakIndex], self._fontSize)

        firstSegment = word[:breakIndex]
        restOfWord = word[breakIndex:]

        return firstSegment, restOfWord

#
# Sparkline
# This Flowable subclass will draw a simple sparkline for the given data
#
class Sparkline(Flowable):
    _data = []
    _min = 0
    _max = 0
    _range = 0
    _dataCnt = 0
    _marginWidth = 0.1 * inch
    width = 0

    def __init__(self, data):
        self._parseData(data)

    def _parseData(self, data):
        """ strips out the ##__SPARKLINE__## item and calculates the bounds of the remaining data """
        self._data = map(float, data.split(',')[1:])
        self._min = min(self._data)
        self._max = max(self._data)
        self._range = self._max - self._min
        self._dataCnt = len(self._data)
        self.width = max([min([float(self._dataCnt) / 50.0 * inch, 2.0 * inch]), inch])
        self.height = 0.2 * inch

        if self._dataCnt < 2:
            logger.warning("Sparkline::_parseData> dataCnt: " + str(self._dataCnt) + " for sparkline data: " + data)

    def wrap(self, availWidth, availHeight):
        """ force height to 0.2 inches TODO: calculate a better height
            set width to show 50 data points per inch, min 1 inch, max 2 inches """
        if self.width > availWidth:
            self.width = availWidth
        if self.height > availHeight:
            self.height = availHeight

        return self.width, self.height

    def draw(self):
        """ draw the sparkline """
        if self._dataCnt < 2:
            return

        totalWidth = self.width - 2.0 * self._marginWidth
        totalHeight = self.height
        deltaWidth = totalWidth / (self._dataCnt - 1)
        lastX = 0
        lastY = 0

        for i in range(self._dataCnt):
            if self._range > 0.0:
                y = (self._data[i] - self._min) / self._range * totalHeight
            else:
                y = totalHeight / 2
            x = i * deltaWidth + self._marginWidth

            if i is 0:
                pass
            else:
                self.canv.line(lastX, lastY, x, y)

            lastX = x
            lastY = y

class EnsureSpaceBetween(Flowable):
    """ Make sure that there is either height space or a frame break inserted into the document """
    # most of this code copied from CondPageBreak 
    def __init__(self, height):
        self.height = height

    def __repr__(self):
        return "EnsureSpaceBetween(%s)" % (self.height)

    def wrap(self, availWidth, availHeight):
        f = self._doctemplateAttr('frame')
        if not f: 
            return availWidth, availHeight
     
        # if we're at the top of the page, we don't need a spacer 
        if f._atTop == 1:
            return 0, 0 
       
        # if we don't have enough space left on the page for the full space, we don't need a spacer 
        if availHeight < self.height:
            f.add_generated_content(FrameBreak)
            return 0, 0
       
        # the spacer fits on the page 
        return 0, self.height

    def draw(self):
        pass

class ColumnSizer(object):
    """ This class encapsulates the algorithms used to determine the width of table columns
        To use, initialize with necessary parameters and then call getWidths() to get column widths  """
    _tableWidth = 0
    _columnPadding = 0
    _cellWidthsByCol = None
    _numCols = 0
    _colWidths = None
    _maxWidths = None

    def __init__(self, cellWidthsByCol, tableWidth=100, columnPadding=10):
        """ cellWidthsByCol is a 2d array of the widths of the table's cells, organized by column """
        self._cellWidthsByCol = cellWidthsByCol
        self._tableWidth = tableWidth
        self._columnPadding = columnPadding
        self._numCols = len(cellWidthsByCol)

        self._maxWidths = []
        # sort the widths
        for colWidths in cellWidthsByCol:
            colWidths.sort() 
            self._maxWidths.append(int(math.ceil(colWidths[-1])) + columnPadding)

    def getWidths(self):
        """ Run through a series of allocation methods with the intent of sizing our tables' columns in a reasonable manner
            This function is memoized """
        if self._colWidths != None:
            return self._colWidths

        self._initColWidths()
        
        # first try setting all columns using the 'simple proportional' allocation method
        # this method tries to allocate space to all unfixed columns that is proportional to their max widths
        # and provides for the max widths. This method will do nothing if it cannot fit all unfixed columns
        numUnfixedCols = self._getNumUnfixedCols()
        if numUnfixedCols > 1:
            self._allocateSimpleProportional()
        
        # if any columns are still unfixed, go through and set all columns that are smaller than the 'fair' width
        # to their max size -- this should free up space for future 'fair' and 'proportional' calculations
        numUnfixedCols = self._getNumUnfixedCols()
        if numUnfixedCols > 1:
            self._allocateByMax()

        # use the simpleProportional allocation method and allow it to set column widths that are smaller than
        # the columns' desired max widths
        numUnfixedCols = self._getNumUnfixedCols()
        if numUnfixedCols > 1:
            self._allocateSimpleProportional(allowLessThanMax=True)    
       
        # if any columns remain unfixed, allocate all remaining space by the 'fair' width 
        numUnfixedCols = self._getNumUnfixedCols()
        if numUnfixedCols > 0:
            self._allocateRemainingSpace()

        return self._colWidths
        
    def _initColWidths(self):
        # the convention here is that any column with 0 width has not yet been set
        self._colWidths = [0]*self._numCols    

    def _getNumUnfixedCols(self):
        """ return the count of unfixed columns. This is based on the convention that an unfixed column as 0 width """
        return self._colWidths.count(0)

    def _allocateSimpleProportional(self, allowLessThanMax=False):
        """ for all unfixed columns, try to set their widths such that they are proportional to their max widths and 
            greater than their max widths (unless allowLessThanMax=True). Only actualy fix any columns widths if we can fix all unfixed columns at this
            time """
        availableSpace = float(self._getAvailableSpace())
        totalColWidths = float(self._getSumUnfixedColMaxWidths())

        # determine the proportional column widths: max/total * availableSpace
        # the colProportions for any already fixed columns will be INVALID
        colProportions = map(lambda x: (float(x) / totalColWidths) * availableSpace, self._maxWidths)
 
        # this is all or nothing -- if a single column's max width is bigger than the proportional space alotted, return without
        # any side effects
        newWidths = self._colWidths[:]
        for index, colWidth in enumerate(self._colWidths):
            if colWidth == 0:
                if not allowLessThanMax and self._maxWidths[index] > colProportions[index]:
                    return
                newWidths[index] = colProportions[index]

        # all the columns will fit! set the column widths to the proportional widths
        self._colWidths = newWidths[:]  

    def _getSumUnfixedColMaxWidths(self):
        """ return the sum of the max widths of all unfixed columns """
        sumMaxWidths = 0

        for index, colWidth in enumerate(self._colWidths):
            if colWidth == 0:
                sumMaxWidths = sumMaxWidths + self._maxWidths[index]

        return sumMaxWidths 

    def _allocateRemainingSpace(self):
        """ assign every unfixed column to use the fair width """
        numUnfixedCols = self._colWidths.count(0)
        if numUnfixedCols == 0:
            return self

        fairWidth = self._getFairWidth()
        for index, colWidth in enumerate(self._colWidths):
            if colWidth == 0:
                self._colWidths[index] = fairWidth 

    def _allocateByMax(self):
        """ for any column whose max width is smaller than the fair width, fix that column to use its max width """
        # preset fixedAtLeastOneWidth to true to allow first iteration
        fixedAtLeastOneWidth = True
        while fixedAtLeastOneWidth and self._colWidths.count(0) > 0:
            # step one, find all columns that fit in less than 'fair width'
            fairWidth = self._getFairWidth()
           
            # find any columns whose maxWidth < fairWidth, and fix those columns' width at maxWidth
            fixedAtLeastOneWidth = False
            for index, maxWidth in enumerate(self._maxWidths):
                if self._colWidths[index] == 0:
                    if maxWidth <= fairWidth:
                        self._colWidths[index] = maxWidth
                        fixedAtLeastOneWidth = True

    def _getFairWidth(self):
        """ return the amount of space available to each unfixed column if we allocate the available space without any proportions """
        unsetNumCols = self._colWidths.count(0)
        if unsetNumCols == 0:
            return 0
        
        return self._getAvailableSpace() / unsetNumCols

    def _getAvailableSpace(self):
        """ return the amount of space that is left after taking account of padding and columns whose width is already fixed """
        availableWidth = self._tableWidth - self._numCols * self._columnPadding # columnPadding is combo of left/right padding, therefore not just in between columns
        for fixedColWidth in self._colWidths:
            availableWidth = availableWidth - fixedColWidth
        
        return availableWidth      

def isNumber(text):
    try:
        float(text)
        return True
    except ValueError:
        return False

# PDFGenDocTemplate
# this subclass of ReportLab's SimpleDocTemplate contains all extra data that 
# we want to get into the footer rendering
#
class PDFGenDocTemplate(SimpleDocTemplate):
    _title = ""
    _logoDrawing = None
    _fontManager = None

    def setFontManager(self, fontManager):
        self._fontManager = fontManager

    def getFontManager(self):
        return self._fontManager

    def setTitle(self, title):
        self._title = title

    def getTitle(self):
        return self._title

    def setTimestamp(self, timestamp):
        self._timeStamp = timestamp

    def getTimestamp(self):
        return self._timeStamp

    def setLogoSvgString(self, logoSvgString):
        svgRenderer = pdfgen_svg.SVGRenderer(logoSvgString, self._fontManager)
        self._logoDrawing = svgRenderer.getDrawing()

    def setLogoDrawing(self, logoDrawing):
        self._logoDrawing = logoDrawing

    def getLogoDrawing(self):
        return self._logoDrawing

#
# _ellipsize
# ellipsize the given text so that only maxCharLength characters are left
# position the ellipsis according to the ellipsisPlacement argument
# RETURNS: the ellipsized text string
#
_ELLIPSIS_PLACEMENT_LEFT = 0
_ELLIPSIS_PLACEMENT_CENTER = 1
_ELLIPSIS_PLACEMENT_RIGHT = 2
_ELLIPSIS = "..."
def _ellipsize(text, maxCharLength, ellipsisPlacement = _ELLIPSIS_PLACEMENT_RIGHT):
    if text == None or len(text) == 0:
        return ""

    if maxCharLength <= 0:
        return _ELLIPSIS

    textLen = len(text)
    numCharsToEllipsize = textLen - maxCharLength
    if numCharsToEllipsize > 0:
        if ellipsisPlacement == _ELLIPSIS_PLACEMENT_LEFT:
            text = _ELLIPSIS + text[numCharsToEllipsize:]
        elif ellipsisPlacement == _ELLIPSIS_PLACEMENT_CENTER:
            text = text[:textLen/2 - numCharsToEllipsize/2] + _ELLIPSIS + text[textLen/2 + numCharsToEllipsize/2:]
        elif ellipsisPlacement == _ELLIPSIS_PLACEMENT_RIGHT:
            text = text[:textLen - numCharsToEllipsize] + _ELLIPSIS
        else:
            text = text[:textLen - numCharsToEllipsize] + _ELLIPSIS

    return text

#
# _footer
# draw all footer elements: splunk logo, title, and, page number
_LOGO_OFFSET = 13
_TITLE_SIZE = 11
_DATE_SIZE = 10
_TEXT_OFFSET = 13
def _footer(canvas, doc):
    splunkLayoutSettings = PAPERSIZES[doc.splunkPaperSize]
    canvas.saveState()
    canvas.setStrokeColorRGB(0.8, 0.8, 0.8)
    canvas.setLineWidth(1)	# hairline
    canvas.line(inch, inch, doc.width + inch, inch)
    canvas.setStrokeColorRGB(0.5,0.5,0.5)
    canvas.setFillColorRGB(0.586,0.586,0.586)
    canvas.drawRightString(doc.width + inch, 0.75 * inch - _TEXT_OFFSET, "Page %d" % (doc.page))
    
    # draw title centered and ellipsized
    ellipsizedTitle = _ellipsize(doc.getTitle(), splunkLayoutSettings['ellipsizedTitleCount'])
    ellipsizedTitleWidth = doc.getFontManager().textWidth(ellipsizedTitle, _TITLE_SIZE) 
    textObject = canvas.beginText(inch + doc.width/2 - ellipsizedTitleWidth/2, 0.75 * inch - _TEXT_OFFSET)
    doc.getFontManager().addTextAndFontToTextObject(textObject, ellipsizedTitle, _TITLE_SIZE)
    canvas.drawText(textObject)

    timestamp = doc.getTimestamp()
    timestampWidth = doc.getFontManager().textWidth(timestamp, _DATE_SIZE)
    textObject = canvas.beginText(inch + doc.width - timestampWidth, inch - _TEXT_OFFSET)
    doc.getFontManager().addTextAndFontToTextObject(textObject, timestamp, _DATE_SIZE)
    canvas.drawText(textObject)

    canvas.restoreState()
    canvas.saveState()
    if doc.getLogoDrawing() != None:
        logoDrawing = doc.getLogoDrawing()
        renderPDF.draw(logoDrawing, canvas, inch, inch - logoDrawing.height - _LOGO_OFFSET, showBoundary=False)
    canvas.restoreState()

#
# _splunkLogoSvg
# this is the hard-coded splunk logo
_splunkLogoSvg = """
<svg version="1.1" id="Layer_1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" x="0" y="0"
 width="87" height="26" viewBox="0 0 263 78" enable-background="new 0 0 263 78" xml:space="preserve">
    <g transform="scale(***logoTransformSize***)">
        <g>
            <g>
                <path fill="#010101" stroke-width="0" stroke-opacity="0" stroke="#010101" d="M29.613,46.603c0,1.725-0.381,3.272-1.09,4.723c-0.738,1.453-1.741,2.679-3.024,3.679
                    c-1.279,1.018-2.82,1.807-4.602,2.368c-1.793,0.57-3.739,0.853-5.856,0.853c-2.531,0-4.782-0.342-6.813-1.022
                    c-2.011-0.695-4.019-1.856-6.029-3.435l3.342-5.418c1.577,1.34,3.02,2.302,4.321,2.932c1.28,0.621,2.603,0.933,3.951,0.933
                    c1.651,0,2.979-0.422,3.97-1.28c1.024-0.845,1.523-2.014,1.523-3.443c0-0.628-0.09-1.205-0.264-1.738
                    c-0.192-0.533-0.533-1.103-1.022-1.666c-0.478-0.585-1.139-1.209-2.002-1.876c-0.84-0.662-1.95-1.487-3.286-2.465
                    c-1.044-0.729-2.042-1.483-3.023-2.253c-0.965-0.77-1.849-1.6-2.678-2.487c-0.777-0.877-1.421-1.85-1.907-2.931
                    c-0.503-1.081-0.729-2.339-0.729-3.738c0-1.591,0.328-3.049,0.993-4.367c0.675-1.321,1.581-2.443,2.74-3.36
                    c1.156-0.947,2.545-1.669,4.171-2.169c1.625-0.525,3.383-0.77,5.271-0.77c2.041,0,3.991,0.271,5.858,0.8
                    c1.885,0.54,3.627,1.31,5.229,2.339l-3.027,4.862c-2.066-1.443-4.219-2.169-6.486-2.169c-1.395,0-2.537,0.363-3.462,1.088
                    c-0.898,0.734-1.346,1.621-1.346,2.72c0,1.021,0.401,1.958,1.199,2.776c0.783,0.833,2.165,1.988,4.121,3.49
                    c1.963,1.436,3.604,2.724,4.918,3.805c1.273,1.088,2.31,2.098,3.035,3.053c0.753,0.974,1.283,1.936,1.567,2.92
                    C29.463,44.322,29.613,45.419,29.613,46.603z"/>
                <path fill="#010101" stroke-width="0" stroke-opacity="0" stroke="#010101" d="M74.654,37.077c0,3.067-0.486,5.863-1.407,8.415c-0.924,2.547-2.217,4.778-3.882,6.688
                    c-1.669,1.913-3.642,3.42-5.896,4.452c-2.287,1.064-4.735,1.592-7.386,1.592c-1.204,0-2.304-0.095-3.355-0.304
                    c-1.025-0.209-1.993-0.557-2.924-1.045c-0.934-0.488-1.854-1.124-2.775-1.895c-0.904-0.777-1.839-1.747-2.831-2.879v24.536
                    h-9.942V18.587h9.942l0.065,5.64c1.806-2.257,3.765-3.922,5.901-4.977c2.1-1.056,4.55-1.581,7.346-1.581
                    c2.547,0,4.855,0.47,6.951,1.428c2.086,0.952,3.898,2.273,5.427,3.983c1.516,1.702,2.704,3.741,3.518,6.118
                    C74.245,31.57,74.654,34.198,74.654,37.077z M63.84,37.492c0-4.252-0.866-7.594-2.579-10.044
                    c-1.725-2.457-4.043-3.687-7.022-3.687c-3.105,0-5.572,1.307-7.395,3.917c-1.815,2.62-2.72,6.15-2.72,10.584
                    c0,4.33,0.892,7.734,2.674,10.229c1.813,2.487,4.243,3.724,7.359,3.724c1.887,0,3.438-0.467,4.645-1.444
                    c1.23-0.954,2.216-2.153,2.963-3.641c0.749-1.472,1.289-3.065,1.601-4.797C63.7,40.601,63.84,38.994,63.84,37.492z"/>
                <path fill="#010101" stroke-width="0" stroke-opacity="0" stroke="#010101" d="M79.086,57.276V0.468h10.2v56.808H79.086z"/>
                <path fill="#010101" stroke-width="0" stroke-opacity="0" stroke="#010101" d="M122.695,57.288l-0.042-5.186c-1.962,2.176-3.975,3.737-6.035,4.685c-2.078,0.97-4.48,1.438-7.211,1.438
                    c-3.053,0-5.624-0.601-7.705-1.807c-2.109-1.222-3.638-3.027-4.555-5.394c-0.252-0.587-0.445-1.176-0.569-1.775
                    c-0.136-0.633-0.251-1.344-0.366-2.135c-0.111-0.821-0.15-1.732-0.18-2.761c-0.042-1.033-0.047-2.295-0.047-3.806V18.521h10.204
                    v22.184c0,1.976,0.093,3.457,0.274,4.515c0.183,1.021,0.494,1.947,0.968,2.782c1.191,2.163,3.285,3.25,6.31,3.25
                    c3.835,0,6.468-1.592,7.935-4.8c0.357-0.841,0.612-1.75,0.781-2.765c0.169-1.007,0.239-2.441,0.239-4.309V18.521h10.185v38.768
                    H122.695z"/>
                <path fill="#010101" stroke-width="0" stroke-opacity="0" stroke="#010101" d="M166.721,57.276V35.149c0-1.955-0.086-3.453-0.274-4.482c-0.188-1.036-0.517-1.947-0.98-2.783
                    c-1.176-2.168-3.294-3.26-6.298-3.26c-1.909,0-3.562,0.411-4.94,1.199c-1.384,0.811-2.397,1.995-3.055,3.527
                    c-0.369,0.881-0.633,1.828-0.772,2.835c-0.112,0.988-0.165,2.42-0.165,4.226v20.866H139.92v-38.67h10.315l0.012,5.177
                    c1.971-2.168,3.98-3.734,6.058-4.686c2.06-0.958,4.469-1.428,7.215-1.428c3.047,0,5.608,0.623,7.719,1.88
                    c2.074,1.266,3.583,3.064,4.52,5.381c0.22,0.57,0.388,1.147,0.544,1.747c0.163,0.585,0.288,1.272,0.389,2.042
                    c0.102,0.777,0.173,1.695,0.196,2.743c0.025,1.062,0.054,2.343,0.054,3.837v21.976H166.721z"/>
                <path fill="#010101" stroke-width="0" stroke-opacity="0" stroke="#010101" d="M209.677,58.055l-15.401-21.374v20.596h-10.282V0.472h10.282v33.355h1.104l13.686-15.876l7.742,3.345
                    l-13.173,14.086l15.579,19.34L209.677,58.055z"/>
            </g>
            <g>
                <path fill="#969796" stroke-width="0" stroke-opacity="0" stroke="#969796" d="M228.03,56.218v-6.803l24.015-11.82l-24.015-11.68v-6.95l30.971,15.537v6.342L228.03,56.218z"/>
            </g>
        </g>
    </g>
</svg>
"""
