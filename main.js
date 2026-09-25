const { app, BrowserWindow } = require("electron");
const path = require("path");
function createWindow(){const win=new BrowserWindow({width:1400,height:900,minWidth:900,minHeight:600,backgroundColor:"#111318",webPreferences:{preload:path.join(__dirname,"preload.js"),contextIsolation:true,nodeIntegration:false}});win.loadFile("src/index.html");win.setMenuBarVisibility(false);}
app.whenReady().then(()=>{createWindow();app.on("activate",()=>{if(BrowserWindow.getAllWindows().length===0)createWindow();});});
app.on("window-all-closed",()=>{if(process.platform!=="darwin")app.quit();});
