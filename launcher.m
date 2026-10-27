#import <Cocoa/Cocoa.h>
#import <AVFoundation/AVFoundation.h>
#import <ApplicationServices/ApplicationServices.h>
#import <Carbon/Carbon.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include "runtime_config.h"

static int pending_hotkey = 0;
static OSStatus on_hotkey(EventHandlerCallRef next, EventRef event, void *context) {
    EventHotKeyID key;
    if (GetEventParameter(event,kEventParamDirectObject,typeEventHotKeyID,NULL,sizeof(key),NULL,&key)==noErr)
        pending_hotkey = (int)key.id;
    return noErr;
}
__attribute__((visibility("default"))) int control_register_hotkeys(void) {
    EventTypeSpec type = {kEventClassKeyboard,kEventHotKeyPressed};
    InstallApplicationEventHandler(&on_hotkey,1,&type,NULL,NULL);
    UInt32 keys[] = {kVK_ANSI_1,kVK_ANSI_2,kVK_ANSI_3,kVK_ANSI_4,kVK_Space};
    int installed = 0;
    for (int i=0;i<5;i++) {
        EventHotKeyRef reference;
        EventHotKeyID identifier = {'Ctrl',(UInt32)(i+1)};
        if (RegisterEventHotKey(keys[i],optionKey,identifier,GetApplicationEventTarget(),0,&reference)==noErr)
            installed |= 1<<i;
    }
    return installed;
}
__attribute__((visibility("default"))) int control_poll_hotkey(void) {
    int value = pending_hotkey;
    pending_hotkey = 0;
    return value;
}

__attribute__((visibility("default"))) int control_camera_status(void) {
    return (int)[AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo];
}
__attribute__((visibility("default"))) int control_microphone_status(void) {
    return (int)[AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio];
}
__attribute__((visibility("default"))) void control_request_camera(void) {
    [AVCaptureDevice requestAccessForMediaType:AVMediaTypeVideo completionHandler:^(BOOL granted) {}];
}
__attribute__((visibility("default"))) void control_request_microphone(void) {
    [AVCaptureDevice requestAccessForMediaType:AVMediaTypeAudio completionHandler:^(BOOL granted) {}];
}
__attribute__((visibility("default"))) void control_request_accessibility(void) {
    NSDictionary *options = @{(__bridge NSString *)kAXTrustedCheckOptionPrompt: @YES};
    AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options);
}

int main(int argc, char **argv) {
    @autoreleasepool {
        NSString *resources = [[NSBundle mainBundle] resourcePath];
        NSString *source = [[[[NSBundle mainBundle] bundlePath] stringByDeletingLastPathComponent] stringByAppendingPathComponent:@"src"];
        NSString *script = [source stringByAppendingPathComponent:@"app.py"];
        if (!getenv("CONTROL_DEV_MODE") || ![[NSFileManager defaultManager] fileExistsAtPath:script]) {
            source = resources;
            script = [resources stringByAppendingPathComponent:@"app.py"];
        }
        NSString *data = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/Control"];
        [[NSFileManager defaultManager] createDirectoryAtPath:data withIntermediateDirectories:YES attributes:nil error:nil];
        NSString *log = [data stringByAppendingPathComponent:@"launch.log"];
        unsigned long long size = [[[NSFileManager defaultManager] attributesOfItemAtPath:log error:nil] fileSize];
        if (size > 512000) {
            [@"" writeToFile:log atomically:YES encoding:NSUTF8StringEncoding error:nil];
        }
        freopen([log fileSystemRepresentation], "a", stderr);
        freopen([log fileSystemRepresentation], "a", stdout);
        setbuf(stdout, NULL);
        setbuf(stderr, NULL);
        setenv("PYTHONHOME", CONTROL_PYHOME, 1);
        NSString *paths = [NSString stringWithFormat:@"%@:%s:%@", source, CONTROL_SITE, resources];
        setenv("PYTHONPATH", [paths fileSystemRepresentation], 1);
        setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
        setenv("OPENCV_AVFOUNDATION_SKIP_AUTH", "1", 1);
        void *lib = dlopen(CONTROL_PYLIB, RTLD_NOW | RTLD_GLOBAL);
        int (*runPython)(int, char **) = lib ? dlsym(lib, "Py_BytesMain") : NULL;
        if (!runPython) {
            NSAlert *alert = [[NSAlert alloc] init];
            alert.messageText = @"Control could not load its Python runtime";
            alert.informativeText = @"Rebuild with build.py using the Python environment used for installation.";
            [alert runModal];
            return 1;
        }
        char **args = calloc((size_t)argc + 2, sizeof(char *));
        args[0] = argv[0];
        args[1] = strdup([script fileSystemRepresentation]);
        for (int i=1; i<argc; ++i) args[i+1] = argv[i];
        int result = runPython(argc+1,args);
        free(args[1]); free(args);
        return result;
    }
}
