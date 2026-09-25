const { contextBridge } = require("electron");
contextBridge.exposeInMainWorld("desktopAPI",{version:"0.1.0"});
