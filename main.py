import math
import random
import sys

import pygame
import pygame_gui
import pymunk

WIDTH = 1280
HEIGHT = 720
PANEL_WIDTH = 310
SIM_WIDTH = WIDTH - PANEL_WIDTH
FPS_LIMIT = 120

BACKGROUND = (18, 21, 28)
GRID = (29, 34, 43)
FLOOR_COLOR = (110, 120, 138)
BOX_COLOR = (74, 144, 226)
CIRCLE_COLOR = (231, 119, 81)
POLY_COLOR = (119, 194, 126)
SELECT_COLOR = (255, 224, 110)
JOINT_COLOR = (235, 205, 95)
SPRING_COLOR = (125, 210, 255)


class PhysicsSandbox:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Physics Sandbox")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()

        self.space = pymunk.Space()
        self.space.iterations = 30
        self.space.sleep_time_threshold = 0.5

        self.gravity_strength = 981.0
        self.gravity_angle = 90.0
        self.paused = False

        self.mouse_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        self.space.add(self.mouse_body)
        self.drag_constraint = None
        self.dragged_body = None

        self.pending_pin_body = None
        self.pending_spring_body = None

        self.spring_stiffness = 1200.0
        self.spring_damping = 90.0

        self.build_static_scene()
        self.build_ui()
        self.apply_gravity()

        for i in range(7):
            x = 150 + i * 85
            y = 90 + (i % 2) * 55
            self.spawn_box((x, y), mass=1.0 + i * 0.25)

    def build_static_scene(self):
        static = self.space.static_body
        floor = pymunk.Segment(static, (20, HEIGHT - 45), (SIM_WIDTH - 20, HEIGHT - 45), 8)
        left = pymunk.Segment(static, (20, 20), (20, HEIGHT - 45), 8)
        right = pymunk.Segment(static, (SIM_WIDTH - 20, 20), (SIM_WIDTH - 20, HEIGHT - 45), 8)

        for shape in (floor, left, right):
            shape.friction = 0.9
            shape.elasticity = 0.25

        self.space.add(floor, left, right)

    def build_ui(self):
        self.manager = pygame_gui.UIManager((WIDTH, HEIGHT))

        self.panel = pygame_gui.elements.UIPanel(
            relative_rect=pygame.Rect(SIM_WIDTH, 0, PANEL_WIDTH, HEIGHT),
            manager=self.manager
        )

        pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(18, 18, 270, 36),
            text="PHYSICS SANDBOX",
            manager=self.manager,
            container=self.panel
        )

        self.pause_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(18, 58, 270, 30),
            text="Simulation : EN COURS",
            manager=self.manager,
            container=self.panel
        )

        pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(18, 105, 270, 26),
            text="Intensité gravité",
            manager=self.manager,
            container=self.panel
        )

        self.gravity_slider = pygame_gui.elements.UIHorizontalSlider(
            relative_rect=pygame.Rect(18, 134, 270, 28),
            start_value=self.gravity_strength,
            value_range=(0.0, 2000.0),
            manager=self.manager,
            container=self.panel
        )

        self.gravity_value = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(18, 163, 270, 24),
            text=f"{self.gravity_strength:.0f} px/s²",
            manager=self.manager,
            container=self.panel
        )

        pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(18, 198, 270, 26),
            text="Angle gravité (0° droite, 90° bas)",
            manager=self.manager,
            container=self.panel
        )

        self.angle_slider = pygame_gui.elements.UIHorizontalSlider(
            relative_rect=pygame.Rect(18, 227, 270, 28),
            start_value=self.gravity_angle,
            value_range=(0.0, 360.0),
            manager=self.manager,
            container=self.panel
        )

        self.angle_value = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(18, 256, 270, 24),
            text=f"{self.gravity_angle:.0f}°",
            manager=self.manager,
            container=self.panel
        )

        pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(18, 292, 270, 24),
            text="Rigidité ressort",
            manager=self.manager,
            container=self.panel
        )

        self.stiffness_slider = pygame_gui.elements.UIHorizontalSlider(
            relative_rect=pygame.Rect(18, 320, 270, 26),
            start_value=self.spring_stiffness,
            value_range=(100.0, 5000.0),
            manager=self.manager,
            container=self.panel
        )

        self.stiffness_value = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(18, 348, 270, 22),
            text=f"{self.spring_stiffness:.0f}",
            manager=self.manager,
            container=self.panel
        )

        pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(18, 378, 270, 24),
            text="Amortissement ressort",
            manager=self.manager,
            container=self.panel
        )

        self.damping_slider = pygame_gui.elements.UIHorizontalSlider(
            relative_rect=pygame.Rect(18, 406, 270, 26),
            start_value=self.spring_damping,
            value_range=(5.0, 300.0),
            manager=self.manager,
            container=self.panel
        )

        self.damping_value = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(18, 434, 270, 22),
            text=f"{self.spring_damping:.0f}",
            manager=self.manager,
            container=self.panel
        )

        self.stats_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(18, 474, 270, 55),
            text="FPS: 0 | Corps: 0",
            manager=self.manager,
            container=self.panel
        )

        self.reset_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(18, 540, 270, 42),
            text="Réinitialiser la scène",
            manager=self.manager,
            container=self.panel
        )

        instructions = (
            "Clic gauche : attraper / déplacer\n"
            "Clic droit : créer un objet\n"
            "P : liaison pivot entre 2 objets\n"
            "S : amortisseur entre 2 objets\n"
            "Espace : pause / reprise"
        )

        pygame_gui.elements.UITextBox(
            html_text=instructions.replace("\n", "<br>"),
            relative_rect=pygame.Rect(18, 595, 270, 105),
            manager=self.manager,
            container=self.panel
        )

    def apply_gravity(self):
        angle = math.radians(self.gravity_angle)
        gx = math.cos(angle) * self.gravity_strength
        gy = math.sin(angle) * self.gravity_strength
        self.space.gravity = (gx, gy)

    def spawn_box(self, position, mass=None):
        mass = mass if mass is not None else random.uniform(0.8, 5.0)
        size = random.randint(28, 54)
        moment = pymunk.moment_for_box(mass, (size, size))
        body = pymunk.Body(mass, moment)
        body.position = position
        shape = pymunk.Poly.create_box(body, (size, size))
        shape.friction = 0.75
        shape.elasticity = 0.3
        shape.collision_type = 1
        self.space.add(body, shape)
        return body

    def spawn_circle(self, position, mass=None):
        mass = mass if mass is not None else random.uniform(0.8, 5.0)
        radius = random.randint(16, 30)
        moment = pymunk.moment_for_circle(mass, 0, radius)
        body = pymunk.Body(mass, moment)
        body.position = position
        shape = pymunk.Circle(body, radius)
        shape.friction = 0.7
        shape.elasticity = 0.55
        shape.collision_type = 1
        self.space.add(body, shape)
        return body

    def spawn_polygon(self, position, mass=None):
        mass = mass if mass is not None else random.uniform(0.8, 5.0)
        r = random.randint(22, 34)
        vertices = [(-r, r), (0, -r), (r, r)]
        moment = pymunk.moment_for_poly(mass, vertices)
        body = pymunk.Body(mass, moment)
        body.position = position
        shape = pymunk.Poly(body, vertices)
        shape.friction = 0.75
        shape.elasticity = 0.35
        shape.collision_type = 1
        self.space.add(body, shape)
        return body

    def spawn_random_object(self, position):
        kind = random.choice(("box", "circle", "poly"))
        if kind == "box":
            return self.spawn_box(position)
        if kind == "circle":
            return self.spawn_circle(position)
        return self.spawn_polygon(position)

    def body_under_mouse(self, position):
        if position[0] >= SIM_WIDTH:
            return None

        query = self.space.point_query_nearest(
            position,
            8,
            pymunk.ShapeFilter()
        )

        if query is None:
            return None

        body = query.shape.body
        if body.body_type != pymunk.Body.DYNAMIC:
            return None
        return body

    def begin_drag(self, position):
        body = self.body_under_mouse(position)
        if body is None:
            return

        self.mouse_body.position = position
        local_anchor = body.world_to_local(position)

        spring = pymunk.DampedSpring(
            self.mouse_body,
            body,
            (0, 0),
            local_anchor,
            0.0,
            1800.0,
            120.0
        )
        spring.max_force = 140000

        self.space.add(spring)
        self.drag_constraint = spring
        self.dragged_body = body

    def end_drag(self):
        if self.drag_constraint is not None and self.drag_constraint in self.space.constraints:
            self.space.remove(self.drag_constraint)

        self.drag_constraint = None
        self.dragged_body = None

    def create_pin_at_mouse(self, position):
        body = self.body_under_mouse(position)
        if body is None:
            return

        if self.pending_pin_body is None:
            self.pending_pin_body = body
            return

        if body is self.pending_pin_body:
            self.pending_pin_body = None
            return

        anchor_a = self.pending_pin_body.world_to_local(position)
        anchor_b = body.world_to_local(position)

        pin = pymunk.PinJoint(
            self.pending_pin_body,
            body,
            anchor_a,
            anchor_b
        )
        pin.distance = 0.0
        pin.max_force = 300000
        self.space.add(pin)
        self.pending_pin_body = None

    def create_spring_at_mouse(self, position):
        body = self.body_under_mouse(position)
        if body is None:
            return

        if self.pending_spring_body is None:
            self.pending_spring_body = body
            return

        if body is self.pending_spring_body:
            self.pending_spring_body = None
            return

        a = self.pending_spring_body.position
        b = body.position
        rest_length = (b - a).length

        spring = pymunk.DampedSpring(
            self.pending_spring_body,
            body,
            (0, 0),
            (0, 0),
            rest_length,
            self.spring_stiffness,
            self.spring_damping
        )
        spring.max_force = 300000
        self.space.add(spring)
        self.pending_spring_body = None

    def reset_scene(self):
        self.end_drag()
        self.pending_pin_body = None
        self.pending_spring_body = None

        for constraint in list(self.space.constraints):
            self.space.remove(constraint)

        dynamic_bodies = [
            body for body in list(self.space.bodies)
            if body.body_type == pymunk.Body.DYNAMIC
        ]

        for body in dynamic_bodies:
            shapes = list(body.shapes)
            self.space.remove(*shapes, body)

        for i in range(7):
            self.spawn_box((150 + i * 85, 90 + (i % 2) * 55), 1.0 + i * 0.25)

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
            if event.ui_element == self.reset_button:
                self.reset_scene()

    def draw_grid(self):
        spacing = 40
        for x in range(0, SIM_WIDTH, spacing):
            pygame.draw.line(self.screen, GRID, (x, 0), (x, HEIGHT), 1)
        for y in range(0, HEIGHT, spacing):
            pygame.draw.line(self.screen, GRID, (0, y), (SIM_WIDTH, y), 1)

    def body_color(self, body, default):
        if body is self.dragged_body:
            return SELECT_COLOR
        if body is self.pending_pin_body:
            return JOINT_COLOR
        if body is self.pending_spring_body:
            return SPRING_COLOR
        return default

    def draw_shapes(self):
        for shape in self.space.shapes:
            if isinstance(shape, pymunk.Segment):
                a = shape.body.local_to_world(shape.a)
                b = shape.body.local_to_world(shape.b)
                pygame.draw.line(
                    self.screen,
                    FLOOR_COLOR,
                    (int(a.x), int(a.y)),
                    (int(b.x), int(b.y)),
                    max(2, int(shape.radius * 2))
                )

            elif isinstance(shape, pymunk.Circle):
                center = shape.body.local_to_world(shape.offset)
                color = self.body_color(shape.body, CIRCLE_COLOR)
                pygame.draw.circle(
                    self.screen,
                    color,
                    (int(center.x), int(center.y)),
                    int(shape.radius)
                )

            elif isinstance(shape, pymunk.Poly):
                vertices = [
                    shape.body.local_to_world(v)
                    for v in shape.get_vertices()
                ]
                points = [(int(v.x), int(v.y)) for v in vertices]
                color = BOX_COLOR if len(points) == 4 else POLY_COLOR
                color = self.body_color(shape.body, color)
                pygame.draw.polygon(self.screen, color, points)

    def draw_constraints(self):
        for constraint in self.space.constraints:
            if constraint is self.drag_constraint:
                continue

            if isinstance(constraint, pymunk.PinJoint):
                a = constraint.a.local_to_world(constraint.anchor_a)
                b = constraint.b.local_to_world(constraint.anchor_b)
                pygame.draw.line(
                    self.screen,
                    JOINT_COLOR,
                    (int(a.x), int(a.y)),
                    (int(b.x), int(b.y)),
                    3
                )
                pygame.draw.circle(self.screen, JOINT_COLOR, (int(a.x), int(a.y)), 5)
                pygame.draw.circle(self.screen, JOINT_COLOR, (int(b.x), int(b.y)), 5)

            elif isinstance(constraint, pymunk.DampedSpring):
                a = constraint.a.local_to_world(constraint.anchor_a)
                b = constraint.b.local_to_world(constraint.anchor_b)
                pygame.draw.line(
                    self.screen,
                    SPRING_COLOR,
                    (int(a.x), int(a.y)),
                    (int(b.x), int(b.y)),
                    2
                )

    def update_stats(self):
        dynamic_count = sum(
            1 for body in self.space.bodies
            if body.body_type == pymunk.Body.DYNAMIC
        )

        fps = self.clock.get_fps()
        self.stats_label.set_text(
            f"FPS: {fps:5.1f} | Corps: {dynamic_count}"
        )

        status = "PAUSE" if self.paused else "EN COURS"
        self.pause_label.set_text(f"Simulation : {status}")

    def run(self):
        running = True

        while running:
            dt = min(self.clock.tick(FPS_LIMIT) / 1000.0, 0.05)
            mouse_pos = pygame.mouse.get_pos()
            self.mouse_body.position = mouse_pos

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                self.manager.process_events(event)
                self.handle_ui_event(event)

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        self.paused = not self.paused
                    elif event.key == pygame.K_p:
                        self.create_pin_at_mouse(mouse_pos)
                    elif event.key == pygame.K_s:
                        self.create_spring_at_mouse(mouse_pos)

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1 and mouse_pos[0] < SIM_WIDTH:
                        self.begin_drag(mouse_pos)
                    elif event.button == 3 and mouse_pos[0] < SIM_WIDTH:
                        self.spawn_random_object(mouse_pos)

                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1:
                        self.end_drag()

            if not self.paused:
                substeps = 4
                sub_dt = dt / substeps
                for _ in range(substeps):
                    self.space.step(sub_dt)

            self.manager.update(dt)
            self.update_stats()

            self.screen.fill(BACKGROUND)
            self.draw_grid()
            self.draw_constraints()
            self.draw_shapes()
            self.manager.draw_ui(self.screen)

            pygame.display.flip()

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    PhysicsSandbox().run()
