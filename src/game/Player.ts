import*as THREE from"three";import type{Settings}from"./types";
export class Player{
readonly camera:THREE.PerspectiveCamera;hp=100;maxHp=100;position=new THREE.Vector3(0,1.75,15);velocity=new THREE.Vector3();yaw=Math.PI;pitch=0;grounded=true;dashCooldown=0;dashPower=16;moveSpeed=8.2;jumpPower=7.2;
private keys=new Set<string>();private settings:Settings;
constructor(camera:THREE.PerspectiveCamera,settings:Settings){this.camera=camera;this.settings=settings;this.sync()}
setSettings(s:Settings){this.settings=s;this.camera.fov=s.fov;this.camera.updateProjectionMatrix()}
onKey(c:string,d:boolean){d?this.keys.add(c):this.keys.delete(c)}
onMouse(dx:number,dy:number){const s=this.settings.sensitivity*.0019;this.yaw-=dx*s;this.pitch=THREE.MathUtils.clamp(this.pitch-dy*s,-1.48,1.48)}
dash(){if(this.dashCooldown>0)return;this.velocity.addScaledVector(new THREE.Vector3(0,0,-1).applyEuler(new THREE.Euler(0,this.yaw,0)),this.dashPower);this.dashCooldown=1.15}
jump(){if(!this.grounded)return;this.grounded=false;this.velocity.y=this.jumpPower}
update(dt:number){this.dashCooldown=Math.max(0,this.dashCooldown-dt);const f=Number(this.keys.has("KeyW")||this.keys.has("KeyZ"))-Number(this.keys.has("KeyS"));const s=Number(this.keys.has("KeyD"))-Number(this.keys.has("KeyA")||this.keys.has("KeyQ"));const wish=new THREE.Vector3(s,0,-f);if(wish.lengthSq()){wish.normalize().applyEuler(new THREE.Euler(0,this.yaw,0));this.velocity.x=THREE.MathUtils.lerp(this.velocity.x,wish.x*this.moveSpeed,.22);this.velocity.z=THREE.MathUtils.lerp(this.velocity.z,wish.z*this.moveSpeed,.22)}else{this.velocity.x*=Math.pow(.002,dt);this.velocity.z*=Math.pow(.002,dt)}this.velocity.y-=18*dt;this.position.addScaledVector(this.velocity,dt);if(this.position.y<1.75){this.position.y=1.75;this.velocity.y=0;this.grounded=true}this.sync()}
damage(a:number){this.hp=Math.max(0,this.hp-a)}heal(a:number){this.hp=Math.min(this.maxHp,this.hp+a)}
forward(){return new THREE.Vector3(0,0,-1).applyEuler(new THREE.Euler(this.pitch,this.yaw,0)).normalize()}
private sync(){this.camera.position.copy(this.position);this.camera.rotation.order="YXZ";this.camera.rotation.y=this.yaw;this.camera.rotation.x=this.pitch}
}
