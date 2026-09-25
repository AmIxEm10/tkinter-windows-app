import json
import math
import os
import queue
import random
import sys
import threading
import time
from pathlib import Path

import imageio.v2 as imageio
import pygame
import pygame_gui
import pymunk

WIDTH, HEIGHT = 1400, 820
PANEL_WIDTH = 330
VIEW_W = WIDTH - PANEL_WIDTH
FPS_LIMIT = 120
FIXED_DT = 1.0 / 120.0

MAX_BODIES = 5000
MAX_PARTICLES = 3500
MAX_FRACTURES_PER_FRAME = 2

BG = (17, 20, 27)
GRID = (28, 33, 42)
STATIC_COLOR = (110, 120, 138)
JOINT_COLOR = (240, 204, 90)
SPRING_COLOR = (105, 210, 255)
REC_COLOR = (255, 45, 45)


def app_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class VideoRecorder:
    def __init__(self):
        self.recording = False
        self.frame_queue = queue.Queue(maxsize=90)
        self.thread = None
        self.writer = None
        self.path = None
        self.last_capture = 0.0
        self.target_fps = 30

    def start(self):
        if self.recording:
            return
        captures = app_root() / "Captures"
        captures.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.path = captures / f"capture_{stamp}.mp4"
        self.recording = True
        self.last_capture = 0.0

        def worker():
            try:
                self.writer = imageio.get_writer(
                    self.path,
                    fps=self.target_fps,
                    codec="libx264",
                    quality=7,
                    macro_block_size=1,
                )
                while self.recording or not self.frame_queue.empty():
                    try:
                        frame = self.frame_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if frame is None:
                        break
                    self.writer.append_data(frame)
            finally:
                if self.writer is not None:
                    self.writer.close()
                    self.writer = None

        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def capture(self, surface):
        if not self.recording:
            return
        now = time.perf_counter()
        if now - self.last_capture < 1.0 / self.target_fps:
            return
        self.last_capture = now
        frame = pygame.surfarray.array3d(surface).swapaxes(0, 1)
        try:
            self.frame_queue.put_nowait(frame)
        except queue.Full:
            pass

    def stop(self):
        if not self.recording:
            return
        self.recording = False
        try:
            self.frame_queue.put_nowait(None)
        except queue.Full:
            pass


class PhysicsSandbox:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Physics Sandbox Ultimate")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 18, bold=True)

        self.space = pymunk.Space()
        self.space.iterations = 22
        self.space.sleep_time_threshold = 0.45
        self.space.collision_slop = 0.15
        self.space.use_spatial_hash(26.0, 20000)

        self.gravity_strength = 981.0
        self.gravity_angle = 90.0
        self.paused = False

        self.camera = pymunk.Vec2d(0, 0)
        self.camera_speed = 650.0
        self.follow_body = None

        self.mouse_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        self.space.add(self.mouse_body)
        self.drag_constraint = None
        self.dragged_body = None

        self.pending_pin = None
        self.pending_spring = None
        self.spring_stiffness = 1300.0
        self.spring_damping = 95.0

        self.spawner_enabled = False
        self.spawner_accum = 0.0
        self.brush_enabled = False
        self.brush_material = "Sand"
        self.brush_accum = 0.0
        self.black_hole_active = False

        self.body_meta = {}
        self.constraint_meta = {}
        self.active_components = []
        self.pending_fractures = []
        self.shock_heat = {}

        self.keybind_target = None
        self.awaiting_keybind = False

        self.dialog_results = queue.Queue()
        self.recorder = VideoRecorder()
        self.rec_blink = 0.0

        self.build_static_scene()
        self.apply_gravity()
        self.setup_collisions()
        self.build_ui()
        self.seed_scene()

    # ---------- coordinate helpers ----------

    def world_to_screen(self, p):
        p = pymunk.Vec2d(p.x, p.y)
        return (int(p.x - self.camera.x), int(p.y - self.camera.y))

    def screen_to_world(self, p):
        return pymunk.Vec2d(p[0] + self.camera.x, p[1] + self.camera.y)

    def in_view(self, shape, margin=80):
        bb = shape.bb
        left = self.camera.x - margin
        right = self.camera.x + VIEW_W + margin
        top = self.camera.y - margin
        bottom = self.camera.y + HEIGHT + margin
        return not (bb.r < left or bb.l > right or bb.t < top or bb.b > bottom)

    # ---------- setup ----------

    def build_static_scene(self):
        s = self.space.static_body
        floor_y = 760
        segments = [
            pymunk.Segment(s, (-4000, floor_y), (8000, floor_y), 10),
            pymunk.Segment(s, (-4000, -1500), (-4000, floor_y), 10),
            pymunk.Segment(s, (8000, -1500), (8000, floor_y), 10),
        ]
        for shape in segments:
            shape.friction = 0.9
            shape.elasticity = 0.25
        self.space.add(*segments)

    def apply_gravity(self):
        a = math.radians(self.gravity_angle)
        self.space.gravity = (
            math.cos(a) * self.gravity_strength,
            math.sin(a) * self.gravity_strength,
        )

    def setup_collisions(self):
        self.space.on_collision(None, None, post_solve=self.on_post_solve)

    def seed_scene(self):
        for i in range(9):
            self.spawn_box((160 + i * 82, 110 + (i % 3) * 50), 1.0 + i * 0.2)
        self.spawn_vehicle((520, 520))

    # ---------- UI ----------

    def build_ui(self):
        self.manager = pygame_gui.UIManager((WIDTH, HEIGHT))
        self.panel = pygame_gui.elements.UIPanel(
            pygame.Rect(VIEW_W, 0, PANEL_WIDTH, HEIGHT), manager=self.manager
        )

        def label(text, y, h=25):
            return pygame_gui.elements.UILabel(
                pygame.Rect(14, y, 300, h), text=text,
                manager=self.manager, container=self.panel
            )

        label("PHYSICS SANDBOX ULTIMATE", 12, 34)
        self.status_label = label("RUNNING", 48)

        self.spawner_button = pygame_gui.elements.UIButton(
            pygame.Rect(14, 82, 145, 36), "Spawner: OFF",
            manager=self.manager, container=self.panel
        )
        self.brush_button = pygame_gui.elements.UIButton(
            pygame.Rect(169, 82, 145, 36), "Brush: OFF",
            manager=self.manager, container=self.panel
        )
        self.brush_type_button = pygame_gui.elements.UIButton(
            pygame.Rect(14, 124, 300, 34), "Material: Sand",
            manager=self.manager, container=self.panel
        )

        self.jelly_button = pygame_gui.elements.UIButton(
            pygame.Rect(14, 166, 145, 34), "Spawn Jelly",
            manager=self.manager, container=self.panel
        )
        self.cloth_button = pygame_gui.elements.UIButton(
            pygame.Rect(169, 166, 145, 34), "Spawn Cloth",
            manager=self.manager, container=self.panel
        )
        self.vehicle_button = pygame_gui.elements.UIButton(
            pygame.Rect(14, 206, 300, 34), "Spawn Vehicle",
            manager=self.manager, container=self.panel
        )

        label("Gravity strength", 250)
        self.gravity_slider = pygame_gui.elements.UIHorizontalSlider(
            pygame.Rect(14, 278, 300, 25), self.gravity_strength, (0.0, 2400.0),
            manager=self.manager, container=self.panel
        )
        self.gravity_value = label(f"{self.gravity_strength:.0f} px/s²", 304, 22)

        label("Gravity angle", 332)
        self.angle_slider = pygame_gui.elements.UIHorizontalSlider(
            pygame.Rect(14, 360, 300, 25), self.gravity_angle, (0.0, 360.0),
            manager=self.manager, container=self.panel
        )
        self.angle_value = label(f"{self.gravity_angle:.0f}°", 386, 22)

        label("Spring stiffness", 414)
        self.stiffness_slider = pygame_gui.elements.UIHorizontalSlider(
            pygame.Rect(14, 442, 300, 25), self.spring_stiffness, (100.0, 6000.0),
            manager=self.manager, container=self.panel
        )
        self.stiffness_value = label(f"{self.spring_stiffness:.0f}", 468, 22)

        label("Spring damping", 496)
        self.damping_slider = pygame_gui.elements.UIHorizontalSlider(
            pygame.Rect(14, 524, 300, 25), self.spring_damping, (5.0, 400.0),
            manager=self.manager, container=self.panel
        )
        self.damping_value = label(f"{self.spring_damping:.0f}", 550, 22)

        self.stats_label = label("FPS 0 | Bodies 0 | Constraints 0", 580, 30)
        self.reset_button = pygame_gui.elements.UIButton(
            pygame.Rect(14, 616, 300, 36), "RESET SCENE",
            manager=self.manager, container=self.panel
        )

        help_text = (
            "<b>Mouse</b><br>"
            "LMB: drag / paint in Brush mode<br>"
            "RMB: spawn random object<br>"
            "MMB: radial explosion<br><br>"
            "<b>Keyboard</b><br>"
            "Space pause • B black hole<br>"
            "P pin • S spring • T thruster<br>"
            "M motor • K assign keybind<br>"
            "L lock camera • ZQSD free camera<br>"
            "F5 save • F9 load • F12 record"
        )
        pygame_gui.elements.UITextBox(
            help_text, pygame.Rect(14, 660, 300, 145),
            manager=self.manager, container=self.panel
        )

    # ---------- object creation ----------

    def register_body(self, body, kind="rigid", material="default", particle=False):
        self.body_meta[body] = {
            "kind": kind,
            "material": material,
            "particle": particle,
        }
        return body

    def can_spawn(self, amount=1):
        return len(self.space.bodies) + amount < MAX_BODIES

    def spawn_box(self, pos, mass=2.0, size=None, material="default"):
        if not self.can_spawn():
            return None
        size = size or random.randint(28, 60)
        moment = pymunk.moment_for_box(mass, (size, size))
        body = pymunk.Body(mass, moment)
        body.position = pos
        shape = pymunk.Poly.create_box(body, (size, size))
        self.apply_material(shape, material)
        self.space.add(body, shape)
        return self.register_body(body, "box", material)

    def spawn_circle(self, pos, mass=1.5, radius=None, material="default", particle=False):
        if not self.can_spawn():
            return None
        radius = radius or random.randint(14, 30)
        moment = pymunk.moment_for_circle(mass, 0, radius)
        body = pymunk.Body(mass, moment)
        body.position = pos
        shape = pymunk.Circle(body, radius)
        self.apply_material(shape, material)
        self.space.add(body, shape)
        return self.register_body(body, "circle", material, particle)

    def spawn_irregular(self, pos, mass=2.5, material="default"):
        if not self.can_spawn():
            return None
        n = random.randint(5, 8)
        verts = []
        for i in range(n):
            a = i * math.tau / n
            r = random.uniform(20, 42)
            verts.append((math.cos(a) * r, math.sin(a) * r))
        moment = pymunk.moment_for_poly(mass, verts)
        body = pymunk.Body(mass, moment)
        body.position = pos
        shape = pymunk.Poly(body, verts)
        self.apply_material(shape, material)
        self.space.add(body, shape)
        return self.register_body(body, "irregular", material)

    def spawn_capsule(self, pos, mass=2.0, material="default"):
        if not self.can_spawn():
            return None
        length = random.uniform(34, 70)
        radius = random.uniform(9, 17)
        moment = pymunk.moment_for_segment(mass, (-length/2, 0), (length/2, 0), radius)
        body = pymunk.Body(mass, moment)
        body.position = pos
        shape = pymunk.Segment(body, (-length/2, 0), (length/2, 0), radius)
        self.apply_material(shape, material)
        self.space.add(body, shape)
        return self.register_body(body, "capsule", material)

    def spawn_cross(self, pos, mass=3.0, material="default"):
        if not self.can_spawn():
            return None
        w, t = random.randint(48, 78), random.randint(12, 22)
        mass_half = mass / 2
        m = pymunk.moment_for_box(mass_half, (w, t)) + pymunk.moment_for_box(mass_half, (t, w))
        body = pymunk.Body(mass, m)
        body.position = pos
        s1 = pymunk.Poly.create_box(body, (w, t))
        s2 = pymunk.Poly.create_box(body, (t, w))
        for s in (s1, s2):
            self.apply_material(s, material)
        self.space.add(body, s1, s2)
        return self.register_body(body, "cross", material)

    def spawn_concave(self, pos, mass=3.0, material="default"):
        if not self.can_spawn():
            return None
        # L-shape decomposed into two convex boxes.
        w, h, t = 62, 62, 20
        m1 = pymunk.moment_for_box(mass * 0.5, (w, t))
        m2 = pymunk.moment_for_box(mass * 0.5, (t, h))
        body = pymunk.Body(mass, m1 + m2)
        body.position = pos
        hshape = pymunk.Poly.create_box(body, (w, t), radius=1)
        vshape = pymunk.Poly.create_box(body, (t, h), radius=1)
        hshape.unsafe_set_vertices([(-w/2, -t/2), (w/2, -t/2), (w/2, t/2), (-w/2, t/2)],
                                   transform=pymunk.Transform(tx=0, ty=h/2-t/2))
        vshape.unsafe_set_vertices([(-t/2, -h/2), (t/2, -h/2), (t/2, h/2), (-t/2, h/2)],
                                   transform=pymunk.Transform(tx=-w/2+t/2, ty=0))
        for s in (hshape, vshape):
            self.apply_material(s, material)
        self.space.add(body, hshape, vshape)
        return self.register_body(body, "concave", material)

    def apply_material(self, shape, material):
        if material == "bouncy":
            shape.elasticity = 1.05
            shape.friction = 0.4
        elif material == "ice":
            shape.elasticity = 0.15
            shape.friction = 0.01
        elif material == "heavy":
            shape.elasticity = 0.05
            shape.friction = 1.0
        elif material == "sand":
            shape.elasticity = 0.02
            shape.friction = 0.82
        elif material == "gravel":
            shape.elasticity = 0.12
            shape.friction = 0.7
        elif material == "water":
            shape.elasticity = 0.02
            shape.friction = 0.05
        else:
            shape.elasticity = 0.3
            shape.friction = 0.72

    def spawn_random_complex(self, pos):
        material = random.choices(
            ["default", "bouncy", "ice", "heavy"],
            weights=[55, 18, 17, 10]
        )[0]
        mass = random.uniform(0.4, 6.0)
        if material == "heavy":
            mass = random.uniform(35, 180)

        fn = random.choice([
            self.spawn_box, self.spawn_circle, self.spawn_irregular,
            self.spawn_capsule, self.spawn_cross, self.spawn_concave
        ])
        body = fn(pos, mass=mass, material=material)
        if body and random.random() < 0.09:
            self.attach_thruster(body, auto=True)
        elif body and random.random() < 0.04:
            self.attach_spin_motor(body, auto=True)
        return body

    # ---------- particles / granular brush ----------

    def particle_count(self):
        return sum(1 for m in self.body_meta.values() if m.get("particle"))

    def paint_particles(self, world_pos, amount=9):
        if self.particle_count() >= MAX_PARTICLES:
            return
        for _ in range(amount):
            if not self.can_spawn() or self.particle_count() >= MAX_PARTICLES:
                break
            jitter = pymunk.Vec2d(random.uniform(-18, 18), random.uniform(-18, 18))
            mat = self.brush_material.lower()
            radius = 3 if mat == "water" else random.randint(3, 5)
            mass = 0.025 if mat == "water" else 0.05
            b = self.spawn_circle(world_pos + jitter, mass, radius, mat, particle=True)
            if b and mat == "water":
                b.velocity = (random.uniform(-25, 25), random.uniform(-15, 15))

    # ---------- interactions / forces ----------

    def body_under_mouse(self, screen_pos):
        if screen_pos[0] >= VIEW_W:
            return None
        world = self.screen_to_world(screen_pos)
        q = self.space.point_query_nearest(world, 9, pymunk.ShapeFilter())
        if q and q.shape.body.body_type == pymunk.Body.DYNAMIC:
            return q.shape.body
        return None

    def begin_drag(self, screen_pos):
        body = self.body_under_mouse(screen_pos)
        if not body:
            return
        world = self.screen_to_world(screen_pos)
        self.mouse_body.position = world
        anchor = body.world_to_local(world)
        c = pymunk.DampedSpring(self.mouse_body, body, (0, 0), anchor, 0, 2200, 135)
        c.max_force = 190000
        self.space.add(c)
        self.drag_constraint = c
        self.dragged_body = body

    def end_drag(self):
        if self.drag_constraint and self.drag_constraint in self.space.constraints:
            self.space.remove(self.drag_constraint)
        self.drag_constraint = None
        self.dragged_body = None

    def explosion(self, world_pos, radius=310, strength=85000):
        for body in list(self.space.bodies):
            if body.body_type != pymunk.Body.DYNAMIC:
                continue
            d = body.position - world_pos
            dist = max(d.length, 1.0)
            if dist > radius:
                continue
            falloff = 1.0 - dist / radius
            impulse = d.normalized() * strength * falloff * max(0.25, min(body.mass, 6))
            body.apply_impulse_at_world_point(impulse, body.position)
            self.shock_heat[body] = 1.0

    def apply_black_hole(self, world_pos, dt):
        radius = 720
        strength = 1200000
        for body in list(self.space.bodies):
            if body.body_type != pymunk.Body.DYNAMIC:
                continue
            d = world_pos - body.position
            dist = max(d.length, 25.0)
            if dist > radius:
                continue
            force = d.normalized() * strength * body.mass / (dist * 0.45)
            body.apply_force_at_world_point(force, body.position)

    # ---------- constraints ----------

    def make_pin(self, body_a, body_b, world_anchor):
        a = body_a.world_to_local(world_anchor)
        b = body_b.world_to_local(world_anchor)
        c = pymunk.PinJoint(body_a, body_b, a, b)
        c.distance = 0
        c.max_force = 350000
        self.space.add(c)
        self.constraint_meta[c] = {"tearable": True, "threshold": 170000}
        return c

    def make_spring(self, a, b):
        rest = (b.position - a.position).length
        c = pymunk.DampedSpring(a, b, (0, 0), (0, 0), rest,
                                self.spring_stiffness, self.spring_damping)
        c.max_force = 350000
        self.space.add(c)
        self.constraint_meta[c] = {"tearable": True, "threshold": 210000}
        return c

    def handle_pin_tool(self, screen_pos):
        body = self.body_under_mouse(screen_pos)
        if not body:
            return
        if self.pending_pin is None:
            self.pending_pin = body
            return
        if body is not self.pending_pin:
            self.make_pin(self.pending_pin, body, self.screen_to_world(screen_pos))
        self.pending_pin = None

    def handle_spring_tool(self, screen_pos):
        body = self.body_under_mouse(screen_pos)
        if not body:
            return
        if self.pending_spring is None:
            self.pending_spring = body
            return
        if body is not self.pending_spring:
            self.make_spring(self.pending_spring, body)
        self.pending_spring = None

    # ---------- active components ----------

    def attach_thruster(self, body, auto=False, key=pygame.K_UP):
        comp = {
            "type": "thruster", "body": body,
            "direction": pymunk.Vec2d(0, -1),
            "force": random.uniform(14000, 30000),
            "key": key, "auto": auto,
        }
        self.active_components.append(comp)
        return comp

    def attach_spin_motor(self, body, auto=False, key=pygame.K_r):
        c = pymunk.SimpleMotor(self.space.static_body, body, random.choice([-7.0, 7.0]))
        c.max_force = random.uniform(25000, 70000)
        self.space.add(c)
        comp = {
            "type": "motor", "body": body, "constraint": c,
            "rate": c.rate, "key": key, "auto": auto,
        }
        self.active_components.append(comp)
        return comp

    def spawn_vehicle(self, pos):
        if not self.can_spawn(3):
            return
        x, y = pos
        chassis = self.spawn_box((x, y), mass=8.0, size=120, material="default")
        if not chassis:
            return
        # Flatten visual chassis.
        shape = next(iter(chassis.shapes))
        shape.unsafe_set_vertices([(-65, -18), (65, -18), (65, 18), (-65, 18)])
        chassis.moment = pymunk.moment_for_box(chassis.mass, (130, 36))

        wheels = []
        for dx in (-46, 46):
            wheel = self.spawn_circle((x + dx, y + 38), mass=2.3, radius=22, material="default")
            if wheel:
                for s in wheel.shapes:
                    s.friction = 1.6
                joint = pymunk.PinJoint(chassis, wheel, (dx, 25), (0, 0))
                joint.distance = 0
                self.space.add(joint)
                self.constraint_meta[joint] = {"tearable": False}
                motor = pymunk.SimpleMotor(chassis, wheel, 0)
                motor.max_force = 85000
                self.space.add(motor)
                self.active_components.append({
                    "type": "motor", "body": wheel, "constraint": motor,
                    "rate": 11.0, "key": pygame.K_UP,
                    "reverse_key": pygame.K_DOWN, "auto": False,
                })
                wheels.append(wheel)

    def update_active_components(self, keys, dt):
        for comp in list(self.active_components):
            body = comp.get("body")
            if body not in self.space.bodies:
                self.active_components.remove(comp)
                continue

            active = comp.get("auto", False) or keys[comp.get("key", pygame.K_UNKNOWN)]
            if comp["type"] == "thruster":
                if active:
                    direction = comp["direction"].rotated(body.angle)
                    body.apply_force_at_local_point(
                        direction * comp["force"], (0, 0)
                    )
            elif comp["type"] == "motor":
                c = comp.get("constraint")
                if c not in self.space.constraints:
                    continue
                reverse_key = comp.get("reverse_key")
                if reverse_key is not None and keys[reverse_key]:
                    c.rate = -abs(comp["rate"])
                elif active:
                    c.rate = abs(comp["rate"])
                elif not comp.get("auto", False):
                    c.rate = 0

    # ---------- soft bodies / cloth ----------

    def spawn_jelly(self, center):
        cols, rows, spacing = 6, 5, 18
        needed = cols * rows
        if not self.can_spawn(needed):
            return
        nodes = []
        cx, cy = center
        for y in range(rows):
            row = []
            for x in range(cols):
                pos = (cx + (x - cols/2) * spacing, cy + (y - rows/2) * spacing)
                b = self.spawn_circle(pos, mass=0.22, radius=6, material="bouncy")
                if b:
                    self.body_meta[b]["kind"] = "jelly_node"
                row.append(b)
            nodes.append(row)

        def spring(a, b, stiffness=1700, damping=55):
            if not a or not b:
                return
            rest = (b.position - a.position).length
            c = pymunk.DampedSpring(a, b, (0, 0), (0, 0), rest, stiffness, damping)
            c.max_force = 140000
            self.space.add(c)
            self.constraint_meta[c] = {"tearable": True, "threshold": 95000}

        for y in range(rows):
            for x in range(cols):
                if x + 1 < cols:
                    spring(nodes[y][x], nodes[y][x+1])
                if y + 1 < rows:
                    spring(nodes[y][x], nodes[y+1][x])
                if x + 1 < cols and y + 1 < rows:
                    spring(nodes[y][x], nodes[y+1][x+1], 1150, 50)
                if x > 0 and y + 1 < rows:
                    spring(nodes[y][x], nodes[y+1][x-1], 1150, 50)

    def spawn_cloth(self, origin):
        cols, rows, spacing = 11, 7, 18
        if not self.can_spawn(cols * rows):
            return
        ox, oy = origin
        nodes = []
        for y in range(rows):
            row = []
            for x in range(cols):
                b = self.spawn_circle((ox + x*spacing, oy + y*spacing),
                                      mass=0.10, radius=4, material="default")
                if b:
                    self.body_meta[b]["kind"] = "cloth_node"
                row.append(b)
            nodes.append(row)

        for y in range(rows):
            for x in range(cols):
                for nx, ny in ((x+1, y), (x, y+1)):
                    if nx < cols and ny < rows:
                        a, b = nodes[y][x], nodes[ny][nx]
                        if a and b:
                            c = pymunk.PinJoint(a, b, (0, 0), (0, 0))
                            c.distance = spacing
                            c.max_force = 50000
                            self.space.add(c)
                            self.constraint_meta[c] = {"tearable": True, "threshold": 33000}

    def process_tearing(self):
        to_remove = []
        for c, meta in list(self.constraint_meta.items()):
            if not meta.get("tearable") or c not in self.space.constraints:
                continue
            threshold = meta.get("threshold", 999999)
            force_est = abs(getattr(c, "impulse", 0.0)) / max(FIXED_DT, 1e-6)
            if isinstance(c, pymunk.DampedSpring):
                pa = c.a.local_to_world(c.anchor_a)
                pb = c.b.local_to_world(c.anchor_b)
                stretch = abs((pb - pa).length - c.rest_length)
                force_est = max(force_est, stretch * c.stiffness)
            if force_est > threshold:
                to_remove.append(c)
        for c in to_remove[:50]:
            if c in self.space.constraints:
                self.space.remove(c)
            self.constraint_meta.pop(c, None)

    # ---------- collision fracture ----------

    def on_post_solve(self, arbiter, space, data):
        impulse = arbiter.total_impulse.length
        if impulse < 9500:
            return
        for shape in arbiter.shapes:
            b = shape.body
            if b.body_type != pymunk.Body.DYNAMIC:
                continue
            meta = self.body_meta.get(b, {})
            if meta.get("particle") or meta.get("kind") in ("jelly_node", "cloth_node", "debris"):
                continue
            if b.mass < 0.4:
                continue
            if b not in self.pending_fractures:
                self.pending_fractures.append(b)
                self.shock_heat[b] = 1.0

    def fracture_body(self, body):
        if body not in self.space.bodies:
            return
        pos = pymunk.Vec2d(body.position.x, body.position.y)
        vel = pymunk.Vec2d(body.velocity.x, body.velocity.y)
        mass = max(body.mass, 0.2)
        self.remove_body(body)

        pieces = min(14, max(7, int(mass * 2)))
        each = max(0.04, mass / pieces)
        for _ in range(pieces):
            if not self.can_spawn():
                break
            angle = random.random() * math.tau
            offset = pymunk.Vec2d(math.cos(angle), math.sin(angle)) * random.uniform(5, 28)
            b = self.spawn_circle(pos + offset, each, random.randint(3, 7), "default")
            if b:
                self.body_meta[b]["kind"] = "debris"
                b.velocity = vel + offset.normalized() * random.uniform(80, 430)
                b.angular_velocity = random.uniform(-12, 12)
                self.shock_heat[b] = 1.0

    def remove_body(self, body):
        constraints = [c for c in list(self.space.constraints) if c.a is body or c.b is body]
        for c in constraints:
            if c in self.space.constraints:
                self.space.remove(c)
            self.constraint_meta.pop(c, None)
        self.active_components = [c for c in self.active_components if c.get("body") is not body]
        shapes = list(body.shapes)
        if shapes:
            self.space.remove(*shapes)
        if body in self.space.bodies:
            self.space.remove(body)
        self.body_meta.pop(body, None)
        self.shock_heat.pop(body, None)

    # ---------- camera ----------

    def update_camera(self, keys, dt):
        if self.follow_body and self.follow_body in self.space.bodies:
            target = self.follow_body.position - pymunk.Vec2d(VIEW_W/2, HEIGHT/2)
            self.camera += (target - self.camera) * min(1.0, dt * 5.5)
            if any(keys[k] for k in (pygame.K_z, pygame.K_q, pygame.K_s, pygame.K_d)):
                self.follow_body = None

        if self.follow_body is None:
            move = pymunk.Vec2d(0, 0)
            if keys[pygame.K_z]:
                move.y -= 1
            if keys[pygame.K_s]:
                move.y += 1
            if keys[pygame.K_q]:
                move.x -= 1
            if keys[pygame.K_d]:
                move.x += 1
            if move.length > 0:
                self.camera += move.normalized() * self.camera_speed * dt

    # ---------- save / load ----------

    def serialize_shape(self, shape):
        base = {
            "friction": shape.friction,
            "elasticity": shape.elasticity,
            "sensor": shape.sensor,
        }
        if isinstance(shape, pymunk.Circle):
            base.update({
                "type": "circle", "radius": shape.radius,
                "offset": [shape.offset.x, shape.offset.y],
            })
        elif isinstance(shape, pymunk.Poly):
            base.update({
                "type": "poly",
                "vertices": [[v.x, v.y] for v in shape.get_vertices()],
                "radius": shape.radius,
            })
        elif isinstance(shape, pymunk.Segment):
            base.update({
                "type": "segment",
                "a": [shape.a.x, shape.a.y],
                "b": [shape.b.x, shape.b.y],
                "radius": shape.radius,
            })
        return base

    def serialize_scene(self):
        bodies = [b for b in self.space.bodies if b.body_type == pymunk.Body.DYNAMIC]
        ids = {b: i for i, b in enumerate(bodies)}
        body_data = []
        for b in bodies:
            body_data.append({
                "id": ids[b],
                "position": [b.position.x, b.position.y],
                "angle": b.angle,
                "velocity": [b.velocity.x, b.velocity.y],
                "angular_velocity": b.angular_velocity,
                "mass": b.mass,
                "moment": b.moment,
                "shapes": [self.serialize_shape(s) for s in b.shapes],
                "meta": self.body_meta.get(b, {}),
            })

        constraints = []
        c_index = {}
        for c in self.space.constraints:
            if c is self.drag_constraint:
                continue
            if c.a not in ids and c.a is not self.space.static_body:
                continue
            if c.b not in ids and c.b is not self.space.static_body:
                continue
            item = {
                "a": "static" if c.a is self.space.static_body else ids[c.a],
                "b": "static" if c.b is self.space.static_body else ids[c.b],
                "meta": self.constraint_meta.get(c, {}),
            }
            if isinstance(c, pymunk.PinJoint):
                item.update({
                    "type": "pin",
                    "anchor_a": [c.anchor_a.x, c.anchor_a.y],
                    "anchor_b": [c.anchor_b.x, c.anchor_b.y],
                    "distance": c.distance,
                    "max_force": c.max_force,
                })
            elif isinstance(c, pymunk.DampedSpring):
                item.update({
                    "type": "spring",
                    "anchor_a": [c.anchor_a.x, c.anchor_a.y],
                    "anchor_b": [c.anchor_b.x, c.anchor_b.y],
                    "rest_length": c.rest_length,
                    "stiffness": c.stiffness,
                    "damping": c.damping,
                    "max_force": c.max_force,
                })
            elif isinstance(c, pymunk.SimpleMotor):
                item.update({
                    "type": "motor",
                    "rate": c.rate,
                    "max_force": c.max_force,
                })
            else:
                continue
            c_index[c] = len(constraints)
            constraints.append(item)

        components = []
        for comp in self.active_components:
            if comp.get("body") not in ids:
                continue
            d = {
                "type": comp["type"],
                "body": ids[comp["body"]],
                "auto": comp.get("auto", False),
                "key": pygame.key.name(comp.get("key", pygame.K_UNKNOWN)),
            }
            if comp["type"] == "thruster":
                d.update({
                    "direction": [comp["direction"].x, comp["direction"].y],
                    "force": comp["force"],
                })
            else:
                d.update({
                    "rate": comp["rate"],
                    "reverse_key": pygame.key.name(comp.get("reverse_key", pygame.K_UNKNOWN))
                    if comp.get("reverse_key") is not None else None,
                    "constraint": c_index.get(comp.get("constraint")),
                })
            components.append(d)

        return {
            "version": 3,
            "gravity_strength": self.gravity_strength,
            "gravity_angle": self.gravity_angle,
            "camera": [self.camera.x, self.camera.y],
            "bodies": body_data,
            "constraints": constraints,
            "components": components,
        }

    def save_scene(self, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.serialize_scene(), f, indent=2)
            print(f"Saved: {path}")
        except Exception as e:
            print("Save error:", e)

    def load_scene(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.clear_dynamic_scene()

            self.gravity_strength = float(data.get("gravity_strength", 981))
            self.gravity_angle = float(data.get("gravity_angle", 90))
            self.apply_gravity()
            cam = data.get("camera", [0, 0])
            self.camera = pymunk.Vec2d(*cam)

            id_to_body = {}
            for bd in data.get("bodies", []):
                mass = max(float(bd["mass"]), 0.0001)
                moment = max(float(bd.get("moment", 1)), 0.0001)
                b = pymunk.Body(mass, moment)
                b.position = bd["position"]
                b.angle = bd["angle"]
                b.velocity = bd["velocity"]
                b.angular_velocity = bd["angular_velocity"]

                shapes = []
                for sd in bd.get("shapes", []):
                    if sd["type"] == "circle":
                        s = pymunk.Circle(b, sd["radius"], sd.get("offset", (0, 0)))
                    elif sd["type"] == "poly":
                        s = pymunk.Poly(b, sd["vertices"], radius=sd.get("radius", 0))
                    elif sd["type"] == "segment":
                        s = pymunk.Segment(b, sd["a"], sd["b"], sd["radius"])
                    else:
                        continue
                    s.friction = sd.get("friction", 0.7)
                    s.elasticity = sd.get("elasticity", 0.3)
                    s.sensor = sd.get("sensor", False)
                    shapes.append(s)

                self.space.add(b, *shapes)
                self.body_meta[b] = bd.get("meta", {})
                id_to_body[int(bd["id"])] = b

            made_constraints = []
            for cd in data.get("constraints", []):
                a = self.space.static_body if cd["a"] == "static" else id_to_body[int(cd["a"])]
                b = self.space.static_body if cd["b"] == "static" else id_to_body[int(cd["b"])]
                if cd["type"] == "pin":
                    c = pymunk.PinJoint(a, b, cd["anchor_a"], cd["anchor_b"])
                    c.distance = cd.get("distance", c.distance)
                elif cd["type"] == "spring":
                    c = pymunk.DampedSpring(
                        a, b, cd["anchor_a"], cd["anchor_b"],
                        cd["rest_length"], cd["stiffness"], cd["damping"]
                    )
                elif cd["type"] == "motor":
                    c = pymunk.SimpleMotor(a, b, cd["rate"])
                else:
                    continue
                c.max_force = cd.get("max_force", float("inf"))
                self.space.add(c)
                self.constraint_meta[c] = cd.get("meta", {})
                made_constraints.append(c)

            for comp in data.get("components", []):
                body = id_to_body.get(int(comp["body"]))
                if not body:
                    continue
                key_name = comp.get("key", "")
                key = pygame.key.key_code(key_name) if key_name else pygame.K_UNKNOWN
                if comp["type"] == "thruster":
                    self.active_components.append({
                        "type": "thruster", "body": body,
                        "direction": pymunk.Vec2d(*comp["direction"]),
                        "force": comp["force"], "key": key,
                        "auto": comp.get("auto", False),
                    })
                elif comp["type"] == "motor":
                    ci = comp.get("constraint")
                    if ci is None or ci >= len(made_constraints):
                        continue
                    rev_name = comp.get("reverse_key")
                    rev = pygame.key.key_code(rev_name) if rev_name else None
                    self.active_components.append({
                        "type": "motor", "body": body,
                        "constraint": made_constraints[ci],
                        "rate": comp["rate"], "key": key,
                        "reverse_key": rev,
                        "auto": comp.get("auto", False),
                    })
        except Exception as e:
            print("Load error:", e)

    def open_save_dialog(self):
        def task():
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                path = filedialog.asksaveasfilename(
                    title="Save Physics Sandbox scene",
                    defaultextension=".json",
                    filetypes=[("Physics scene", "*.json"), ("JSON", "*.json")],
                    initialfile="scene.json",
                )
                root.destroy()
                if path:
                    self.dialog_results.put(("save", path))
            except Exception as e:
                print("Dialog error:", e)
        threading.Thread(target=task, daemon=True).start()

    def open_load_dialog(self):
        def task():
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                path = filedialog.askopenfilename(
                    title="Load Physics Sandbox scene",
                    filetypes=[("Physics scene", "*.json"), ("JSON", "*.json")],
                )
                root.destroy()
                if path:
                    self.dialog_results.put(("load", path))
            except Exception as e:
                print("Dialog error:", e)
        threading.Thread(target=task, daemon=True).start()

    def process_dialog_results(self):
        while True:
            try:
                action, path = self.dialog_results.get_nowait()
            except queue.Empty:
                break
            if action == "save":
                self.save_scene(path)
            elif action == "load":
                self.load_scene(path)

    # ---------- scene maintenance ----------

    def clear_dynamic_scene(self):
        self.end_drag()
        self.pending_pin = None
        self.pending_spring = None
        self.follow_body = None
        for c in list(self.space.constraints):
            if c is not self.drag_constraint:
                self.space.remove(c)
        for b in list(self.space.bodies):
            if b.body_type == pymunk.Body.DYNAMIC:
                shapes = list(b.shapes)
                if shapes:
                    self.space.remove(*shapes)
                self.space.remove(b)
        self.body_meta.clear()
        self.constraint_meta.clear()
        self.active_components.clear()
        self.pending_fractures.clear()
        self.shock_heat.clear()

    def reset_scene(self):
        self.clear_dynamic_scene()
        self.camera = pymunk.Vec2d(0, 0)
        self.seed_scene()

    # ---------- UI events ----------

    def handle_ui_event(self, event):
        if event.type == pygame_gui.UI_HORIZONTAL_SLIDER_MOVED:
            if event.ui_element == self.gravity_slider:
                self.gravity_strength = float(event.value)
                self.gravity_value.set_text(f"{self.gravity_strength:.0f} px/s²")
                self.apply_gravity()
            elif event.ui_element == self.angle_slider:
                self.gravity_angle = float(event.value)
                self.angle_value.set_text(f"{self.gravity_angle:.0f}°")
                self.apply_gravity()
            elif event.ui_element == self.stiffness_slider:
                self.spring_stiffness = float(event.value)
                self.stiffness_value.set_text(f"{self.spring_stiffness:.0f}")
            elif event.ui_element == self.damping_slider:
                self.spring_damping = float(event.value)
                self.damping_value.set_text(f"{self.spring_damping:.0f}")

        elif event.type == pygame_gui.UI_BUTTON_PRESSED:
            if event.ui_element == self.spawner_button:
                self.spawner_enabled = not self.spawner_enabled
                self.spawner_button.set_text(f"Spawner: {'ON' if self.spawner_enabled else 'OFF'}")
            elif event.ui_element == self.brush_button:
                self.brush_enabled = not self.brush_enabled
                self.brush_button.set_text(f"Brush: {'ON' if self.brush_enabled else 'OFF'}")
            elif event.ui_element == self.brush_type_button:
                order = ["Sand", "Gravel", "Water"]
                self.brush_material = order[(order.index(self.brush_material) + 1) % len(order)]
                self.brush_type_button.set_text(f"Material: {self.brush_material}")
            elif event.ui_element == self.jelly_button:
                self.spawn_jelly(self.screen_to_world((VIEW_W//2, 190)))
            elif event.ui_element == self.cloth_button:
                self.spawn_cloth(self.screen_to_world((VIEW_W//2 - 100, 120)))
            elif event.ui_element == self.vehicle_button:
                self.spawn_vehicle(self.screen_to_world((VIEW_W//2, 520)))
            elif event.ui_element == self.reset_button:
                self.reset_scene()

    # ---------- rendering ----------

    def heat_color(self, body, base=(90, 125, 170)):
        speed = body.velocity.length
        thermal = min(1.0, speed / 1250.0)
        thermal = max(thermal, self.shock_heat.get(body, 0.0))
        r = int(base[0] + (255 - base[0]) * thermal)
        g = int(base[1] + (65 - base[1]) * thermal)
        b = int(base[2] + (30 - base[2]) * thermal)
        if body is self.dragged_body:
            return (255, 225, 90)
        if body is self.pending_pin:
            return JOINT_COLOR
        if body is self.pending_spring:
            return SPRING_COLOR
        return (r, max(0, g), max(0, b))

    def draw_grid(self):
        spacing = 50
        start_x = -int(self.camera.x) % spacing
        start_y = -int(self.camera.y) % spacing
        for x in range(start_x, VIEW_W, spacing):
            pygame.draw.line(self.screen, GRID, (x, 0), (x, HEIGHT))
        for y in range(start_y, HEIGHT, spacing):
            pygame.draw.line(self.screen, GRID, (0, y), (VIEW_W, y))

    def draw_constraints(self):
        for c in self.space.constraints:
            if c is self.drag_constraint:
                continue
            if isinstance(c, pymunk.PinJoint):
                a = c.a.local_to_world(c.anchor_a)
                b = c.b.local_to_world(c.anchor_b)
                sa, sb = self.world_to_screen(a), self.world_to_screen(b)
                pygame.draw.line(self.screen, JOINT_COLOR, sa, sb, 2)
            elif isinstance(c, pymunk.DampedSpring):
                a = c.a.local_to_world(c.anchor_a)
                b = c.b.local_to_world(c.anchor_b)
                sa, sb = self.world_to_screen(a), self.world_to_screen(b)
                pygame.draw.line(self.screen, SPRING_COLOR, sa, sb, 1)

    def draw_shapes(self):
        for shape in self.space.shapes:
            if not self.in_view(shape):
                continue
            body = shape.body
            if body.body_type == pymunk.Body.STATIC:
                color = STATIC_COLOR
            else:
                meta = self.body_meta.get(body, {})
                base = (95, 145, 205)
                if meta.get("particle"):
                    mat = meta.get("material")
                    base = {"sand": (190, 165, 100), "gravel": (130, 130, 135),
                            "water": (60, 135, 235)}.get(mat, base)
                elif meta.get("kind") == "jelly_node":
                    base = (185, 90, 225)
                elif meta.get("kind") == "cloth_node":
                    base = (95, 200, 155)
                color = self.heat_color(body, base)

            if isinstance(shape, pymunk.Circle):
                p = body.local_to_world(shape.offset)
                sp = self.world_to_screen(p)
                pygame.draw.circle(self.screen, color, sp, max(2, int(shape.radius)))
            elif isinstance(shape, pymunk.Segment):
                a = self.world_to_screen(body.local_to_world(shape.a))
                b = self.world_to_screen(body.local_to_world(shape.b))
                pygame.draw.line(self.screen, color, a, b, max(2, int(shape.radius * 2)))
            elif isinstance(shape, pymunk.Poly):
                pts = [self.world_to_screen(body.local_to_world(v)) for v in shape.get_vertices()]
                if len(pts) >= 3:
                    pygame.draw.polygon(self.screen, color, pts)

    def draw_thrusters(self, keys):
        for comp in self.active_components:
            if comp["type"] != "thruster":
                continue
            body = comp["body"]
            if body not in self.space.bodies:
                continue
            active = comp.get("auto", False) or keys[comp.get("key", pygame.K_UNKNOWN)]
            if not active:
                continue
            p = self.world_to_screen(body.position)
            d = comp["direction"].rotated(body.angle)
            tail = (int(p[0] - d.x * 26), int(p[1] - d.y * 26))
            pygame.draw.line(self.screen, (255, 150, 45), p, tail, 5)

    # ---------- main loop ----------

    def run(self):
        running = True
        accumulator = 0.0

        while running:
            frame_dt = min(self.clock.tick(FPS_LIMIT) / 1000.0, 0.05)
            accumulator += frame_dt
            mouse = pygame.mouse.get_pos()
            world_mouse = self.screen_to_world(mouse)
            self.mouse_body.position = world_mouse
            keys = pygame.key.get_pressed()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                self.manager.process_events(event)
                self.handle_ui_event(event)

                if event.type == pygame.KEYDOWN:
                    if self.awaiting_keybind and self.keybind_target:
                        self.keybind_target["key"] = event.key
                        self.awaiting_keybind = False
                        self.keybind_target = None
                        continue

                    if event.key == pygame.K_SPACE:
                        self.paused = not self.paused
                    elif event.key == pygame.K_p:
                        self.handle_pin_tool(mouse)
                    elif event.key == pygame.K_s and not keys[pygame.K_LCTRL]:
                        self.handle_spring_tool(mouse)
                    elif event.key == pygame.K_t:
                        b = self.body_under_mouse(mouse)
                        if b:
                            self.attach_thruster(b, auto=False, key=pygame.K_UP)
                    elif event.key == pygame.K_m:
                        b = self.body_under_mouse(mouse)
                        if b:
                            self.attach_spin_motor(b, auto=False, key=pygame.K_r)
                    elif event.key == pygame.K_k:
                        b = self.body_under_mouse(mouse)
                        if b:
                            candidates = [c for c in self.active_components if c.get("body") is b]
                            if candidates:
                                self.keybind_target = candidates[-1]
                                self.awaiting_keybind = True
                    elif event.key == pygame.K_l:
                        self.follow_body = self.body_under_mouse(mouse)
                    elif event.key == pygame.K_F5:
                        self.open_save_dialog()
                    elif event.key == pygame.K_F9:
                        self.open_load_dialog()
                    elif event.key == pygame.K_F12:
                        if self.recorder.recording:
                            self.recorder.stop()
                        else:
                            self.recorder.start()

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1 and mouse[0] < VIEW_W and not self.brush_enabled:
                        self.begin_drag(mouse)
                    elif event.button == 3 and mouse[0] < VIEW_W:
                        self.spawn_random_complex(world_mouse)
                    elif event.button == 2 and mouse[0] < VIEW_W:
                        self.explosion(world_mouse)

                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self.end_drag()

            self.black_hole_active = keys[pygame.K_b]
            self.update_camera(keys, frame_dt)
            self.process_dialog_results()

            if self.spawner_enabled:
                self.spawner_accum += frame_dt
                while self.spawner_accum >= 0.035:
                    self.spawner_accum -= 0.035
                    x = self.camera.x + random.uniform(30, VIEW_W - 30)
                    y = self.camera.y - random.uniform(30, 240)
                    self.spawn_random_complex((x, y))

            if self.brush_enabled and pygame.mouse.get_pressed()[0] and mouse[0] < VIEW_W:
                self.brush_accum += frame_dt
                if self.brush_accum >= 0.016:
                    self.brush_accum = 0
                    self.paint_particles(world_mouse, amount=10)

            self.update_active_components(keys, frame_dt)
            if self.black_hole_active and mouse[0] < VIEW_W:
                self.apply_black_hole(world_mouse, frame_dt)

            if not self.paused:
                while accumulator >= FIXED_DT:
                    self.space.step(FIXED_DT)
                    self.process_tearing()
                    accumulator -= FIXED_DT
            else:
                accumulator = 0.0

            for _ in range(min(MAX_FRACTURES_PER_FRAME, len(self.pending_fractures))):
                self.fracture_body(self.pending_fractures.pop(0))

            for body in list(self.shock_heat):
                self.shock_heat[body] *= 0.94
                if self.shock_heat[body] < 0.03 or body not in self.space.bodies:
                    self.shock_heat.pop(body, None)

            self.manager.update(frame_dt)

            bodies = sum(1 for b in self.space.bodies if b.body_type == pymunk.Body.DYNAMIC)
            self.status_label.set_text(
                f"{'PAUSED' if self.paused else 'RUNNING'} | {'REC' if self.recorder.recording else 'IDLE'}"
            )
            self.stats_label.set_text(
                f"FPS {self.clock.get_fps():.0f} | Bodies {bodies} | Constraints {len(self.space.constraints)}"
            )

            self.screen.fill(BG)
            self.draw_grid()
            self.draw_constraints()
            self.draw_shapes()
            self.draw_thrusters(keys)

            if self.black_hole_active and mouse[0] < VIEW_W:
                pygame.draw.circle(self.screen, (120, 70, 210), mouse, 24, 3)

            self.manager.draw_ui(self.screen)

            if self.recorder.recording:
                self.rec_blink += frame_dt
                if int(self.rec_blink * 3) % 2 == 0:
                    pygame.draw.circle(self.screen, REC_COLOR, (28, 28), 8)
                    txt = self.font.render("REC", True, REC_COLOR)
                    self.screen.blit(txt, (43, 18))

            self.recorder.capture(self.screen)
            pygame.display.flip()

        self.recorder.stop()
        pygame.quit()


if __name__ == "__main__":
    PhysicsSandbox().run()
