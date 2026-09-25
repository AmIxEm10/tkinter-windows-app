import type * as THREE from "three";
export type Quality="low"|"medium"|"high";
export interface Settings{fov:number;sensitivity:number;quality:Quality}
export interface Progress{bestScore:number;runs:number;unlockedSpells:string[]}
export interface Damageable{mesh:THREE.Object3D;hp:number;maxHp:number;frozenUntil:number;alive:boolean;type:string;velocity:THREE.Vector3}
export interface Destructible{mesh:THREE.Mesh;hp:number;explosive:boolean;velocity:THREE.Vector3;grabbed:boolean}
export type SpellId="impact"|"braise"|"givre"|"faille"|"arc"|"nova";
export interface SpellDefinition{id:SpellId;name:string;cooldown:number;color:number;damage:number}
