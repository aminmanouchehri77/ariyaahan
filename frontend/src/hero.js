// Interactive 3D hero: floating steel sections lit by a molten-orange glow,
// with rising sparks and gentle pointer parallax. Progressive enhancement:
// the page shows a pre-rendered poster until this module takes over.
//
// Scroll flight: as the visitor scrolls, every section leaves the hero,
// shrinks, fades and flies into the card of its own category below (the
// I-beam into «تیرآهن», the rebar bundle into «میلگرد», …), where it melts
// into the card's product render. It is scrubbed by scroll, so scrolling
// back up reverses it.
import { THREE, MATERIALS, createRenderer, createStudio } from './steel.js';
import {
  CAMERA_Y, CAMERA_Z, CLUSTER_FLOAT, FLOAT_AMPLITUDE, TILT_AMPLITUDE, heroFraming, heroLayout,
} from './hero-layout.js';

function sparkTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 64;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  gradient.addColorStop(0, 'rgba(255,240,210,1)');
  gradient.addColorStop(0.25, 'rgba(255,150,60,0.9)');
  gradient.addColorStop(1, 'rgba(255,80,10,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(canvas);
}

// Which category card each hero piece flies into (by category slug).
const FLIGHT_TARGETS = {
  beam: 'beam', bundle: 'rebar', sheets: 'steel-sheet', tube: 'pipe', box: 'profiles', angle: 'angles-channels',
};
// Pose the pieces settle into: lying almost flat, turned like the card renders.
const LANDING_POSE = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.32, 0.95, 0.04));

const clamp01 = (v) => Math.min(1, Math.max(0, v));
const smooth = (a, b, v) => {
  const t = clamp01((v - a) / (b - a));
  return t * t * (3 - 2 * t);
};
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

export function mountHero(container, { onReady, flight = true } = {}) {
  const canvas = document.createElement('canvas');
  canvas.className = flight ? 'hero-canvas hero-canvas--fixed' : 'hero-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  // The flight canvas is a fixed layer above the page sections (and below
  // the hero text) so the pieces can travel down into the category cards.
  (flight ? document.body : container).appendChild(canvas);
  const sizeSource = flight ? canvas : container;

  const renderer = createRenderer(canvas, { alpha: true });
  renderer.shadowMap.enabled = false;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  const scene = createStudio(renderer, { floor: false });
  scene.environmentIntensity = 0.5;
  scene.traverse((light) => {
    if (light.isDirectionalLight) light.intensity = 0.9;
  });

  const camera = new THREE.PerspectiveCamera(62, 1, 0.05, 60);
  camera.position.set(0, CAMERA_Y, CAMERA_Z);

  const glow = new THREE.PointLight(0xff5a14, 40, 12, 1.4);
  glow.position.set(-1.5, -1.8, 1.5);
  scene.add(glow);

  const world = new THREE.Group();
  scene.add(world);

  const pieces = heroLayout();
  const meshes = pieces.map((piece, index) => {
    // One material per piece so each can fade on its own during the flight.
    const material = MATERIALS[piece.material]();
    material.transparent = flight;
    const mesh = new THREE.Mesh(piece.geometry, material);
    mesh.position.set(...piece.pos);
    mesh.rotation.set(...piece.rot);
    const phase = index * 0.9;
    const speed = 0.42 + (index % 3) * 0.09;
    mesh.userData = {
      base: mesh.position.clone(), rot: mesh.rotation.clone(), phase, speed,
      slug: FLIGHT_TARGETS[piece.key], restPx: 1, progress: 0,
    };
    world.add(mesh);
    return mesh;
  });

  // Centre the composition on its own bounding box so framing does not
  // depend on hand-tuned offsets.
  const layoutBox = new THREE.Box3().setFromObject(world);
  const layoutCenter = layoutBox.getCenter(new THREE.Vector3());

  // Sparks
  const SPARKS = 340;
  const positions = new Float32Array(SPARKS * 3);
  const velocities = new Float32Array(SPARKS * 3);
  const resetSpark = (i, initial = false) => {
    // Sparks rise from the lower part of the bundle and drift through it.
    const size = layoutBox.getSize(new THREE.Vector3());
    positions[i * 3] = layoutBox.min.x + Math.random() * size.x;
    positions[i * 3 + 1] = initial ? layoutBox.min.y + Math.random() * size.y : layoutBox.min.y + Math.random() * size.y * 0.35;
    positions[i * 3 + 2] = layoutCenter.z + 0.6 + Math.random() * 1.6;
    velocities[i * 3] = 0.15 + Math.random() * 0.5;
    velocities[i * 3 + 1] = 0.6 + Math.random() * 1.4;
    velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.3;
  };
  for (let i = 0; i < SPARKS; i += 1) resetSpark(i, true);
  const sparkGeometry = new THREE.BufferGeometry();
  sparkGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const sparks = new THREE.Points(sparkGeometry, new THREE.PointsMaterial({
    size: 0.11, map: sparkTexture(), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, color: 0xffa060,
  }));
  world.add(sparks);

  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  const onPointer = (event) => {
    const rect = container.getBoundingClientRect();
    pointer.tx = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
    pointer.ty = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
  };
  window.addEventListener('pointermove', onPointer, { passive: true });

  const resize = () => {
    const { width, height } = sizeSource.getBoundingClientRect();
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    const framing = heroFraming(layoutBox.getSize(new THREE.Vector3()), layoutCenter, width, height);
    camera.aspect = framing.aspect;
    camera.fov = framing.fov;
    world.scale.setScalar(framing.scale);
    world.position.set(...framing.position);
    const scale = framing.scale;
    world.userData.baseY = world.position.y;
    world.userData.scale = scale;
    camera.updateProjectionMatrix();
    // Longest on-screen size each piece can take (its bounding sphere at
    // its own depth), so the flight can shrink it to fit its card whatever
    // its orientation on landing.
    world.updateMatrixWorld(true);
    const halfFov = THREE.MathUtils.degToRad(camera.fov / 2);
    for (const mesh of meshes) {
      mesh.geometry.computeBoundingSphere();
      const centre = mesh.geometry.boundingSphere.center.clone().applyMatrix4(mesh.matrixWorld);
      const distance = Math.max(0.5, camera.position.z - centre.z);
      const pxPerUnit = height / (2 * distance * Math.tan(halfFov));
      mesh.userData.restPx = Math.max(2 * mesh.geometry.boundingSphere.radius * scale * pxPerUnit, 1);
    }
    viewport.width = width;
    viewport.height = height;
  };
  const viewport = { width: 1, height: 1 };
  const observer = new ResizeObserver(resize);
  observer.observe(sizeSource);
  resize();

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const narrow = window.matchMedia('(max-width: 900px)');
  let visible = true;
  let flightDone = false;
  const cards = {};
  if (flight) {
    for (const media of document.querySelectorAll('[data-flight-target]')) {
      cards[media.dataset.flightTarget] = cards[media.dataset.flightTarget] || media;
    }
  }
  const ray = new THREE.Vector3();
  const target = new THREE.Vector3();

  // Scroll flight: per piece, progress runs 0 → 1 between the top of the
  // page and the moment its card reaches the middle of the screen.
  const fly = (intro) => {
    const scrollY = window.scrollY;
    const heroHeight = container.getBoundingClientRect().height || viewport.height;
    const leave = clamp01(scrollY / (heroHeight * 0.6));
    let done = true;
    for (const mesh of meshes) {
      const data = mesh.userData;
      const media = cards[data.slug];
      const rect = media && media.offsetParent !== null ? media.getBoundingClientRect() : null;
      const landAt = rect
        ? Math.max(rect.top + scrollY + rect.height / 2 - viewport.height * 0.5, heroHeight * 0.55)
        : heroHeight * 0.8;
      const p = clamp01(scrollY / landAt);
      data.progress = p;
      if (p < 1) done = false;
      const e = easeInOut(p);
      // Everything shrinks as soon as it leaves the hero, not only when its
      // own card comes close.
      const out = Math.max(p, leave);
      const shrink = 1 - (1 - out) ** 3;
      if (rect && p > 0) {
        // Point on the piece's own depth plane that projects onto the card.
        const ndcX = ((rect.left + rect.width / 2) / viewport.width) * 2 - 1;
        const ndcY = -(((rect.top + rect.height * 0.52) / viewport.height) * 2 - 1);
        const restZ = world.position.z + data.base.z * world.scale.x;
        ray.set(ndcX, ndcY, 0.5).unproject(camera).sub(camera.position).normalize();
        target.copy(camera.position).addScaledVector(ray, (restZ - camera.position.z) / ray.z);
        target.sub(world.position).divideScalar(world.scale.x);
        mesh.position.lerp(target, e);
        // Phone cards are full width, so pieces land smaller there and also
        // dip in size mid-flight to keep the text they cross readable.
        const fit = Math.min(1, (rect.width * (narrow.matches ? 0.5 : 0.72)) / data.restPx);
        const dip = narrow.matches ? 1 - 0.4 * Math.sin(Math.PI * e) : 1;
        mesh.scale.setScalar((1 + (fit - 1) * shrink) * dip);
        mesh.quaternion.slerp(LANDING_POSE, e);
      } else if (p > 0) {
        // No card for this piece: it drifts down and fades away.
        mesh.position.y -= p * 3;
        mesh.scale.setScalar(1 - 0.6 * shrink);
      } else {
        mesh.scale.setScalar(1);
      }
      // Paler as it travels, gone once it has merged into the card.
      const pale = narrow.matches ? 0.55 : 0.4;
      mesh.material.opacity = (1 - pale * smooth(0, 0.7, out)) * (1 - smooth(0.8, 1, p));
      mesh.visible = mesh.material.opacity > 0.01;
      if (media) {
        const card = media.closest('.category-card');
        media.style.setProperty('--land', smooth(0.7, 1, p).toFixed(3));
        if (p > 0.92) card?.classList.add('is-landed');
        else if (p < 0.6) card?.classList.remove('is-landed');
      }
    }
    sparks.material.opacity = 1 - smooth(0, 0.5, leave);
    glow.intensity *= 1 - leave;
    world.rotation.y *= 1 - leave;
    world.rotation.x *= 1 - leave;
    // On phones the pieces sit behind the hero text, so they stay dim until
    // they leave it.
    const dim = narrow.matches ? 0.32 + 0.68 * smooth(0.05, 0.45, leave) : 1;
    canvas.style.opacity = (intro * dim).toFixed(3);
    canvas.style.visibility = done ? 'hidden' : 'visible';
    flightDone = done;
  };
  let introStart = 0;
  let frame = 0;
  let last = performance.now();
  const clock = { t: 0 };

  const render = (now) => {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    clock.t += dt;
    pointer.x += (pointer.tx - pointer.x) * 0.04;
    pointer.y += (pointer.ty - pointer.y) * 0.04;
    // The bundle moves as one rigid body, so its pieces keep their spacing.
    world.rotation.y = -pointer.x * 0.07 + Math.sin(clock.t * 0.15) * 0.03;
    world.rotation.x = pointer.y * 0.035;
    world.position.y = world.userData.baseY + Math.sin(clock.t * 0.35) * CLUSTER_FLOAT * world.userData.scale;
    for (const mesh of meshes) {
      const { base, rot, phase, speed } = mesh.userData;
      // Start every frame from the resting pose; the scroll flight is
      // applied on top of it, so it never accumulates.
      mesh.position.copy(base);
      mesh.position.y += Math.sin(clock.t * speed + phase) * FLOAT_AMPLITUDE;
      mesh.rotation.set(rot.x, rot.y, rot.z + Math.sin(clock.t * speed * 0.6 + phase) * TILT_AMPLITUDE);
    }
    for (let i = 0; i < SPARKS; i += 1) {
      positions[i * 3] += velocities[i * 3] * dt;
      positions[i * 3 + 1] += velocities[i * 3 + 1] * dt;
      positions[i * 3 + 2] += velocities[i * 3 + 2] * dt;
      velocities[i * 3 + 1] -= 0.25 * dt;
      if (positions[i * 3 + 1] > layoutBox.max.y + 0.5 || positions[i * 3 + 1] < layoutBox.min.y - 0.6) resetSpark(i);
    }
    sparkGeometry.attributes.position.needsUpdate = true;
    glow.intensity = 36 + Math.sin(clock.t * 3.1) * 4 + Math.sin(clock.t * 7.3) * 2;
    if (flight) {
      if (!introStart) introStart = now;
      fly(smooth(0, 1200, now - introStart));
      if (flightDone) return;
    }
    renderer.render(scene, camera);
  };

  const loop = (now) => {
    const idle = flight ? (!visible && flightDone) : !visible;
    if (idle || document.hidden) {
      frame = 0;
      return;
    }
    render(now);
    frame = requestAnimationFrame(loop);
  };
  const start = () => {
    if (frame || reduceMotion.matches) return;
    last = performance.now();
    frame = requestAnimationFrame(loop);
  };

  render(performance.now());
  if (onReady) onReady();
  const io = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    if (visible) start();
  });
  io.observe(container);
  if (flight) {
    window.addEventListener('scroll', start, { passive: true });
    window.addEventListener('resize', start, { passive: true });
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) start(); });
  reduceMotion.addEventListener?.('change', () => (reduceMotion.matches ? null : start()));
  start();
}

// Auto-mount
const host = document.querySelector('[data-hero-3d]');
if (host) {
  const lowPower = navigator.connection?.saveData || (navigator.hardwareConcurrency && navigator.hardwareConcurrency < 3);
  const gl = (() => {
    try {
      const probe = document.createElement('canvas');
      return !!(probe.getContext('webgl2') || probe.getContext('webgl'));
    } catch (_) {
      return false;
    }
  })();
  if (gl && !lowPower) {
    try {
      const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      mountHero(host, { onReady: () => host.classList.add('is-live'), flight: !reduce });
    } catch (_) {
      /* keep the poster image */
    }
  }
}
