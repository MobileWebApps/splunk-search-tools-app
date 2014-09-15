splunk-search-tools-app
=============================================

This app extends splunk search with extra commands.


 Command      | Type       | Description
:------------ |:-----------|:----------------------------------------------------
 encode       | streaming  | encodes search fields on a variety of algos [base64, md5, sha, dsa, or any other hashlib algo]
 decode       | streaming  | decodes base64 search fields
 deviceatlas  | streaming  | outputs browser and mobile device properties based on the useragent field


## Example queries
```
    # Device Atlas
	sourcetype=access_combined | head 1 | deviceatlas osName browserName model primaryHardwareType manufacturer yearReleased

    # All commands
    sourcetype=access_combined | head 1 | deviceatlas browserName | encode browserName | decode browserName_base64 | encode browserName type=md5
```


## Installation

+ Package the app by running the `package.sh`.

+ Install the app by expanding the resulting `target/splunk-search-tools-app.tgz` into `$SPLUNK_HOME/etc/apps/`.

+ (Re)start Splunk so that the app is recognized.

+ you can also use the Splunk web interface to install `splunk-search-tools-app.tgz`  



The app is tested on Splunk 6. 

## References  
[1] [splunk-sdk-python](http://dev.splunk.com/view/python-sdk/SP-CAAAEBB) 

[2] [app.conf](http://docs.splunk.com/Documentation/Splunk/latest/Admin/Appconf app.conf)  

[3] [commands.conf](http://docs.splunk.com/Documentation/Splunk/latest/Admin/Commandsconf)  

[4] [Python Logging HOWTO](http://docs.python.org/2/howto/logging.html)  

[5] [ConfigParser—Configuration file parser](http://docs.python.org/2/library/configparser.html)

[6] [searchbnf.conf](http://docs.splunk.com/Documentation/Splunk/latest/admin/Searchbnfconf)

[7] [Set permissions in the file system](http://goo.gl/1oDT7r)


## Device Atlas Properties 
```
    e.g: 
    user_agent = "Mozilla/5.0 (Linux; U; Android 2.3.3; en-gb; GT-I9100 Build/GINGERBREAD) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1"

    browserName:Android Browser
    model:GT-I9100 Galaxy S2
    primaryHardwareType:Mobile Phone
    marketingName:Galaxy S2
    vendor:Samsung
    manufacturer:Samsung
    browserRenderingEngine:WebKit
    yearReleased:2011
    osAndroid:1
    osWebOs:0
    osWindowsPhone:0
    osWindowsMobile:0
    isRobot:0
    isTablet:0
    isMobilePhone:1
    isGamesConsole:0
    isMediaPlayer:0
    displayWidth:480
    usableDisplayWidth:480
    usableDisplayHeight:800
    js.geoLocation:1
    js.deviceOrientation:0
    js.indexedDB:0
    js.modifyDom:1
    js.supportEvents:1
    js.supportBasicJavaScript:1

    markup.xhtmlMp12:1
    lteAdvanced:0
    umts:1
    3gp.aac.lc:1
    mp3:1
    3gp.amr.wb:0
    html.canvas:1
    cookieSupport:1
    osRim:0
    midiPolyphonic:1
    image.Gif87:1
    3gp.h264.level10b:1
    drmOmaForwardLock:1
    wmv:0
    jsr118:0
    markup.xhtmlBasic10:1
    mp4.h264.level13:1
    mp4.h264.level11:1
    markup.xhtmlMp10:1
    displayColorDepth:24
    uriSchemeTel:1
    isBrowser:0
    js.webWorkers:0
    3gp.amr.nb:1
    amr:1
    stream.3gp.h264.level12:1
    stream.3gp.h264.level13:1
    stream.3gp.h264.level10:1
    stream.3gp.h264.level11:1
    supportsClientSide:1
    nfc:0
    html.svg:0
    osLinux:0
    osOsx:0
    mp4.aac.lc:1
    gprs:1
    memoryLimitEmbeddedMedia:0
    jsr30:0
    jsr37:0
    isTV:0
    qcelp:0
    css.transforms:1
    hspaEvolved:1
    isFeedReader:0
    js.supportEventListener:1
    osSymbian:0
    mobileDevice:1
    js.localStorage:1
    stream.mp4.h264.level13:1
    stream.mp4.h264.level11:1
    isFilter:0
    osBada:0
    js.applicationCache:1
    osName:Android
    js.supportConsoleLog:1
    js.touchEvents:1
    lte:0
    js.xhr:1
    uriSchemeSmsTo:1
    memoryLimitDownload:0
    diagonalScreenSize:4.3
    markup.wml1:0
    html.inlinesvg:0
    isSetTopBox:0
    isSpam:0
    css.animations:1
    memoryLimitMarkup:2000000
    js.sessionStorage:1
    html.audio:1
    camera:8.0
    qcelpInVideo:0
    https:1
    drmOmaSeparateDelivery:1
    image.Jpg:1
    uriSchemeSms:1
    stream.mp4.aac.lc:1
    js.modifyCss:1
    stream.3gp.h264.level10b:1
    drmOmaCombinedDelivery:1
    vCardDownload:0
    aac:1
    isEReader:0
    js.webGl:0
    html.video:1
    css.transitions:1
    isDownloader:0
    displayHeight:800
    js.json:1
    stream.3gp.h263:1
    jqm:1
    3gp.h264.level13:1
    3gp.h264.level12:1
    3gp.h264.level11:1
    3gp.h264.level10:1
    js.webSockets:0
    stream.3gp.aac.lc:1
    image.Gif89a:1
    touchScreen:1
    isChecker:0
    js.deviceMotion:0
    osWindowsRt:0
    id:2410065
    jsr139:0
    css.columns:1
    js.querySelector:1
    displayPpi:217
    midiMonophonic:1
    image.Png:1
    markup.xhtmlMp11:1
    stream.3gp.amr.wb:1
    stream.3gp.amr.nb:1
    osWindows:0
    js.webSqlDatabase:1
    3gp.h263:1
    osiOs:0
    hsdpa:1
    osVersion:2.3.3
    browserVersion:4.0
    devicePixelRatio:1.5
    edge:1
```