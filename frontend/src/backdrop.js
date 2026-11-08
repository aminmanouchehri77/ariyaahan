// Studio backdrop for product cards: a seamless cyclorama with a
// diamond-plate steel floor, top spotlight and a warm molten rim glow.
// Rendered once to WebP by the render pipeline; cards layer the transparent
// product renders on top of it.
import { THREE } from './steel.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

function diamondPlateCanvas(size = 1024, cells = 22) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  // Height map: mid grey base + raised lozenges in alternating directions.
  ctx.fillStyle = 'rgb(118,118,118)';
  ctx.fillRect(0, 0, size, size);
  const step = size / cells;
  for (let row = 0; row < cells; row += 1) {
    for (let col = 0; col < cells; col += 1) {
      const cx = col * step + step / 2;
      const cy = row * step + step / 2;
      const angle = (row + col) % 2 ? Math.PI / 4 : -Math.PI / 4;
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(angle);
      const gradient = ctx.createLinearGradient(-step * 0.38, 0, step * 0.38, 0);
      gradient.addColorStop(0, 'rgb(120,120,120)');
      gradient.addColorStop(0.5, 'rgb(250,250,250)');
      gradient.addColorStop(1, 'rgb(120,120,120)');
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.ellipse(0, 0, step * 0.4, step * 0.09, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
  }
  // Fine brushed noise.
  const image = ctx.getImageData(0, 0, size, size);
  for (let i = 0; i < image.data.length; i += 4) {
    const noise = (Math.random() - 0.5) * 18;
    image.data[i] += noise; image.data[i + 1] += noise; image.data[i + 2] += noise;
  }
  ctx.putImageData(image, 0, 0);
  return canvas;
}

function heightToNormal(source, strength = 3) {
  const { width, height } = source;
  const src = source.getContext('2d').getImageData(0, 0, width, height).data;
  const canvas = document.createElement('canvas');
  canvas.width = width; canvas.height = height;
  const ctx = canvas.getContext('2d');
  const out = ctx.createImageData(width, height);
  const h = (x, y) => src[(((y + height) % height) * width + ((x + width) % width)) * 4] / 255;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const dx = (h(x + 1, y) - h(x - 1, y)) * strength;
      const dy = (h(x, y + 1) - h(x, y - 1)) * strength;
      const len = Math.hypot(dx, dy, 1);
      const i = (y * width + x) * 4;
      out.data[i] = ((-dx / len) * 0.5 + 0.5) * 255;
      out.data[i + 1] = ((-dy / len) * 0.5 + 0.5) * 255;
      out.data[i + 2] = ((1 / len) * 0.5 + 0.5) * 255;
      out.data[i + 3] = 255;
    }
  }
  ctx.putImageData(out, 0, 0);
  return canvas;
}

export function renderBackdrop(canvas, { width = 1200, height = 900, tone = 'dark' } = {}) {
  canvas.width = width; canvas.height = height;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(width, height, false);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = tone === 'dark' ? 1.0 : 1.25;
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = tone === 'dark' ? 0.08 : 0.45;
  scene.background = new THREE.Color(tone === 'dark' ? 0x0d0f12 : 0x2a2f36);

  // Cyclorama profile (z, y): floor toward the camera, quarter-circle cove,
  // then a vertical back wall.
  const radius = 2.2;
  const profilePoints = [new THREE.Vector3(0, 0, 7), new THREE.Vector3(0, 0, 0.4)];
  for (let i = 0; i <= 24; i += 1) {
    const angle = (Math.PI / 2) * (i / 24);
    profilePoints.push(new THREE.Vector3(0, radius - Math.cos(angle) * radius, -Math.sin(angle) * radius));
  }
  profilePoints.push(new THREE.Vector3(0, 9, -radius));
  const curve = new THREE.CatmullRomCurve3(profilePoints, false, 'centripetal');
  // Build the cyc as an extruded ribbon across X.
  const ribbon = new THREE.BufferGeometry();
  const segments = 160;
  const across = 2;
  const positions = [];
  const uvs = [];
  const indices = [];
  const sampled = curve.getSpacedPoints(segments);
  let length = 0;
  sampled.forEach((point, index) => {
    if (index) length += point.distanceTo(sampled[index - 1]);
    for (let j = 0; j < across; j += 1) {
      const x = j === 0 ? -10 : 10;
      positions.push(x, point.y, point.z);
      uvs.push((x + 10) / 20 * 6, length / 3);
    }
  });
  for (let i = 0; i < segments; i += 1) {
    const a = i * 2, b = a + 1, c = a + 2, d = a + 3;
    indices.push(a, c, b, b, c, d);
  }
  ribbon.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  ribbon.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  ribbon.setIndex(indices);
  ribbon.computeVertexNormals();

  const plateHeight = diamondPlateCanvas();
  const normal = new THREE.CanvasTexture(heightToNormal(plateHeight, 2.4));
  normal.wrapS = normal.wrapT = THREE.RepeatWrapping;
  normal.repeat.set(1.2, 1.2);
  const material = new THREE.MeshPhysicalMaterial({
    color: tone === 'dark' ? 0x33373d : 0x8a919a,
    metalness: 0.6,
    roughness: 0.62,
    side: THREE.DoubleSide,
    normalMap: normal,
    normalScale: new THREE.Vector2(0.55, 0.55),
    clearcoat: 0,
  });
  const cyc = new THREE.Mesh(ribbon, material);
  scene.add(cyc);

  const spot = new THREE.SpotLight(0xfff1e6, 170, 20, Math.PI / 7, 1, 1.5);
  spot.position.set(0, 9, 4.6);
  spot.target.position.set(0, 0, 0.2);
  scene.add(spot, spot.target);
  const warm = new THREE.PointLight(0xff6a2a, 16, 9, 1.8);
  warm.position.set(-2.8, 0.25, 0.8);
  scene.add(warm);
  const cool = new THREE.PointLight(0x9fb4d6, 3, 9, 1.8);
  cool.position.set(3.6, 1.8, -1.2);
  scene.add(cool);
  scene.add(new THREE.HemisphereLight(0xc9d3df, 0x1a1c20, 0.05));

  const camera = new THREE.PerspectiveCamera(32, width / height, 0.1, 50);
  camera.position.set(0, 2.1, 6.4);
  camera.lookAt(0, 0.35, -0.6);
  renderer.render(scene, camera);
  const url = canvas.toDataURL('image/webp', 0.86);
  renderer.dispose();
  return url;
}

window.renderBackdrop = (options) => renderBackdrop(document.createElement('canvas'), options);
window.backdropReady = true;
