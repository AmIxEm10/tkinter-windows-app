import type{Progress,Settings}from"./types";
const SK="cc.settings.v2",PK="cc.progress.v2";
export const defaultSettings:Settings={fov:88,sensitivity:.55,quality:"high"};
export const defaultProgress:Progress={bestScore:0,runs:0,unlockedSpells:["impact","braise","givre","faille","arc","nova"]};
export function loadSettings():Settings{try{return{...defaultSettings,...JSON.parse(localStorage.getItem(SK)??"{}")}}catch{return{...defaultSettings}}}
export function saveSettings(v:Settings){localStorage.setItem(SK,JSON.stringify(v))}
export function loadProgress():Progress{try{return{...defaultProgress,...JSON.parse(localStorage.getItem(PK)??"{}")}}catch{return{...defaultProgress}}}
export function saveProgress(v:Progress){localStorage.setItem(PK,JSON.stringify(v))}
