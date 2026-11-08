// Interactive 3D hero: floating steel sections lit by a molten-orange glow,
// with rising sparks and gentle pointer parallax. Progressive enhancement:
// the page shows a pre-rendered poster until this module takes over.
import { THREE, MATERIALS, createRenderer, createStudio } from './steel.js';
import { FLOAT_AMPLITUDE, TILT_AMPLITUDE, heroLayout } from './hero-layout.js';

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

export function mountHero(container, { onReady } = {}) {
  const canvas = document.createElement('canvas');
  canvas.className = 'hero-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  container.appendChild(canvas);

  const renderer = createRenderer(canvas, { alpha: true });
  renderer.shadowMap.enabled = false;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  const scene = createStudio(renderer, { floor: false });
  scene.environmentIntensity = 0.5;
  scene.traverse((light) => {
    if (light.isDirectionalLight) light.intensity = 0.9;
  });

  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 60);
  camera.position.set(0, 0.3, 9);

  const glow = new THREE.PointLight(0xff5a14, 40, 12, 1.4);
  glow.position.set(-1.5, -1.8, 1.5);
  scene.add(glow);

  const world = new THREE.Group();
  scene.add(world);

  const pieces = heroLayout();
  const materials = {};
  const meshes = pieces.map((piece, index) => {
    const mesh = new THREE.Mesh(piece.geometry, materials[piece.material] || (materials[piece.material] = MATERIALS[piece.material]()));
    mesh.position.set(...piece.pos);
    mesh.rotation.set(...piece.rot);
    // Rebars float together as one bundle so their spacing never changes.
    const phase = piece.group === 'rebars' ? 3.1 : index * 0.9;
    const speed = piece.group === 'rebars' ? 0.3 : 0.22 + (index % 3) * 0.07;
    mesh.userData = { base: mesh.position.clone(), rot: mesh.rotation.clone(), phase, speed };
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
    positions[i * 3] = -2.5 + Math.random() * 3.2;
    positions[i * 3 + 1] = initial ? -3 + Math.random() * 6 : -2.8;
    positions[i * 3 + 2] = -1 + Math.random() * 3;
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
    const { width, height } = container.getBoundingClientRect();
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    // Keep the composition on the visual (left in RTL) side on wide screens,
    // centred behind the content on narrow ones.
    const wide = width > 900;
    const scale = wide ? 0.66 : 0.52;
    const target = wide ? new THREE.Vector3(-2.15, 0.05, 0) : new THREE.Vector3(0.35, 1.0, 0);
    world.scale.setScalar(scale);
    world.position.set(
      target.x - layoutCenter.x * scale,
      target.y - layoutCenter.y * scale,
      -layoutCenter.z * scale,
    );
    camera.fov = wide ? 34 : 44;
    camera.updateProjectionMatrix();
  };
  const observer = new ResizeObserver(resize);
  observer.observe(container);
  resize();

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let visible = true;
  let frame = 0;
  let last = performance.now();
  const clock = { t: 0 };

  const render = (now) => {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    clock.t += dt;
    pointer.x += (pointer.tx - pointer.x) * 0.04;
    pointer.y += (pointer.ty - pointer.y) * 0.04;
    world.rotation.y = -pointer.x * 0.12 + Math.sin(clock.t * 0.15) * 0.05;
    world.rotation.x = pointer.y * 0.06;
    for (const mesh of meshes) {
      const { base, rot, phase, speed } = mesh.userData;
      mesh.position.y = base.y + Math.sin(clock.t * speed + phase) * FLOAT_AMPLITUDE;
      mesh.rotation.z = rot.z + Math.sin(clock.t * speed * 0.6 + phase) * TILT_AMPLITUDE;
    }
    for (let i = 0; i < SPARKS; i += 1) {
      positions[i * 3] += velocities[i * 3] * dt;
      positions[i * 3 + 1] += velocities[i * 3 + 1] * dt;
      positions[i * 3 + 2] += velocities[i * 3 + 2] * dt;
      velocities[i * 3 + 1] -= 0.25 * dt;
      if (positions[i * 3 + 1] > 3.2 || positions[i * 3 + 1] < -3.2) resetSpark(i);
    }
    sparkGeometry.attributes.position.needsUpdate = true;
    glow.intensity = 36 + Math.sin(clock.t * 3.1) * 4 + Math.sin(clock.t * 7.3) * 2;
    renderer.render(scene, camera);
  };

  const loop = (now) => {
    if (!visible || document.hidden) {
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
      mountHero(host, { onReady: () => host.classList.add('is-live') });
    } catch (_) {
      /* keep the poster image */
    }
  }
}
