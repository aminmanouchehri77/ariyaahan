// Procedural steel products for the hero scene and the catalog renders.
// Everything is generated from geometry + procedural textures: no external
// models or photos, so every image on the site is original.
import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

// ---------------------------------------------------------------------------
// Materials
// ---------------------------------------------------------------------------

function noiseCanvas(size, { streak = 0, base = 128, spread = 70, seed = 1 } = {}) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const image = ctx.createImageData(size, size);
  let s = seed * 9301 + 49297;
  const rand = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
  const rows = new Float32Array(size);
  for (let y = 0; y < size; y += 1) rows[y] = rand();
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      // Brushed look: mostly per-row variation (streaks) plus fine grain.
      const v = base + (rows[y] - 0.5) * spread * streak + (rand() - 0.5) * spread * (1 - streak * 0.7);
      const i = (y * size + x) * 4;
      image.data[i] = image.data[i + 1] = image.data[i + 2] = Math.max(0, Math.min(255, v));
      image.data[i + 3] = 255;
    }
  }
  ctx.putImageData(image, 0, 0);
  return canvas;
}

const textureCache = new Map();
function brushedTexture(key, options, repeat = [1, 6]) {
  if (!textureCache.has(key)) {
    const texture = new THREE.CanvasTexture(noiseCanvas(256, options));
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.colorSpace = THREE.NoColorSpace;
    textureCache.set(key, texture);
  }
  const texture = textureCache.get(key).clone();
  texture.repeat.set(repeat[0], repeat[1]);
  texture.needsUpdate = true;
  return texture;
}

export function steelMaterial({ color = 0x8d949c, roughness = 0.42, repeat = [1, 6], seed = 1, clearcoat = 0 } = {}) {
  return new THREE.MeshPhysicalMaterial({
    color,
    metalness: 1,
    roughness,
    roughnessMap: brushedTexture(`r${seed}`, { streak: 0.85, base: 150, spread: 90, seed }, repeat),
    clearcoat,
    clearcoatRoughness: 0.4,
    envMapIntensity: 1.1,
  });
}

export const MATERIALS = {
  rebar: () => steelMaterial({ color: 0x7a6e64, roughness: 0.5, seed: 2 }),
  mill: () => steelMaterial({ color: 0x7c848d, roughness: 0.42, seed: 3 }),
  bright: () => steelMaterial({ color: 0xb4bac1, roughness: 0.28, seed: 4, clearcoat: 0.3 }),
  galvanized: () => steelMaterial({ color: 0xc8ced4, roughness: 0.33, seed: 5, repeat: [3, 3] }),
  dark: () => steelMaterial({ color: 0x575d64, roughness: 0.5, seed: 6 }),
  pellet: () => new THREE.MeshStandardMaterial({ color: 0x4a3a31, roughness: 0.92, metalness: 0.15 }),
  alloy: () => steelMaterial({ color: 0xa7a39b, roughness: 0.38, seed: 7, repeat: [2, 2] }),
  ember: () => new THREE.MeshStandardMaterial({
    color: 0x3a1c10, emissive: 0xff4d12, emissiveIntensity: 1.15, roughness: 0.55, metalness: 0.5,
  }),
};

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

function extrude(shape, depth, bevel = 0.012) {
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth, bevelEnabled: bevel > 0, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 2, curveSegments: 18,
  });
  geometry.translate(0, 0, -depth / 2);
  geometry.computeVertexNormals();
  return geometry;
}

export function iBeamGeometry(length = 4, h = 0.42, b = 0.22, tw = 0.035, tf = 0.05) {
  const s = new THREE.Shape();
  s.moveTo(-b / 2, -h / 2);
  s.lineTo(b / 2, -h / 2);
  s.lineTo(b / 2, -h / 2 + tf);
  s.lineTo(tw / 2, -h / 2 + tf);
  s.lineTo(tw / 2, h / 2 - tf);
  s.lineTo(b / 2, h / 2 - tf);
  s.lineTo(b / 2, h / 2);
  s.lineTo(-b / 2, h / 2);
  s.lineTo(-b / 2, h / 2 - tf);
  s.lineTo(-tw / 2, h / 2 - tf);
  s.lineTo(-tw / 2, -h / 2 + tf);
  s.lineTo(-b / 2, -h / 2 + tf);
  s.closePath();
  return extrude(s, length, 0.006);
}

export function angleGeometry(length = 4, a = 0.22, t = 0.03) {
  const s = new THREE.Shape();
  s.moveTo(0, 0);
  s.lineTo(a, 0);
  s.lineTo(a, t);
  s.lineTo(t, t);
  s.lineTo(t, a);
  s.lineTo(0, a);
  s.closePath();
  return extrude(s, length, 0.005);
}

export function channelGeometry(length = 4, h = 0.3, b = 0.12, t = 0.03) {
  const s = new THREE.Shape();
  s.moveTo(0, 0);
  s.lineTo(b, 0);
  s.lineTo(b, t);
  s.lineTo(t, t);
  s.lineTo(t, h - t);
  s.lineTo(b, h - t);
  s.lineTo(b, h);
  s.lineTo(0, h);
  s.closePath();
  return extrude(s, length, 0.005);
}

export function boxSectionGeometry(length = 4, w = 0.22, h = 0.22, t = 0.018, r = 0.025) {
  const s = new THREE.Shape();
  const rounded = (shape, x, y, width, height, radius) => {
    shape.moveTo(x + radius, y);
    shape.lineTo(x + width - radius, y);
    shape.quadraticCurveTo(x + width, y, x + width, y + radius);
    shape.lineTo(x + width, y + height - radius);
    shape.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
    shape.lineTo(x + radius, y + height);
    shape.quadraticCurveTo(x, y + height, x, y + height - radius);
    shape.lineTo(x, y + radius);
    shape.quadraticCurveTo(x, y, x + radius, y);
  };
  rounded(s, -w / 2, -h / 2, w, h, r);
  const hole = new THREE.Path();
  rounded(hole, -w / 2 + t, -h / 2 + t, w - 2 * t, h - 2 * t, Math.max(0.004, r - t));
  s.holes.push(hole);
  return extrude(s, length, 0.003);
}

export function tubeGeometry(length = 4, outer = 0.11, wall = 0.012) {
  const s = new THREE.Shape();
  s.absarc(0, 0, outer, 0, Math.PI * 2, false);
  const hole = new THREE.Path();
  hole.absarc(0, 0, outer - wall, 0, Math.PI * 2, true);
  s.holes.push(hole);
  return extrude(s, length, 0.003);
}

export function rebarGeometry(length = 4, radius = 0.045) {
  // Core bar + transverse ribs + two longitudinal ribs, merged in one mesh.
  const parts = [];
  const core = new THREE.CylinderGeometry(radius, radius, length, 20, 1, false);
  core.rotateX(Math.PI / 2);
  parts.push(core);
  const spacing = radius * 1.35;
  const count = Math.floor(length / spacing);
  for (let i = 0; i < count; i += 1) {
    const rib = new THREE.TorusGeometry(radius * 1.02, radius * 0.14, 5, 18, Math.PI * 0.92);
    rib.rotateZ((i % 2 ? 0.1 : -0.1) + (i % 2) * Math.PI);
    rib.rotateY(0.22 * (i % 2 ? 1 : -1));
    rib.translate(0, 0, -length / 2 + i * spacing + spacing / 2);
    parts.push(rib);
  }
  for (const side of [-1, 1]) {
    const longitudinal = new THREE.BoxGeometry(radius * 0.22, radius * 0.22, length);
    longitudinal.translate(side * radius * 0.98, 0, 0);
    parts.push(longitudinal);
  }
  return mergeGeometries(parts);
}

export function mergeGeometries(geometries) {
  // Minimal merge (non-indexed) to avoid pulling BufferGeometryUtils.
  const prepared = geometries.map((g) => (g.index ? g.toNonIndexed() : g));
  let total = 0;
  for (const g of prepared) total += g.attributes.position.count;
  const position = new Float32Array(total * 3);
  const normal = new Float32Array(total * 3);
  const uv = new Float32Array(total * 2);
  let offset = 0;
  for (const g of prepared) {
    if (!g.attributes.normal) g.computeVertexNormals();
    position.set(g.attributes.position.array, offset * 3);
    normal.set(g.attributes.normal.array, offset * 3);
    if (g.attributes.uv) uv.set(g.attributes.uv.array, offset * 2);
    offset += g.attributes.position.count;
  }
  const merged = new THREE.BufferGeometry();
  merged.setAttribute('position', new THREE.BufferAttribute(position, 3));
  merged.setAttribute('normal', new THREE.BufferAttribute(normal, 3));
  merged.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  return merged;
}

function hexPack(count, spacing) {
  // Positions in a roughly hexagonal bundle cross-section.
  const points = [[0, 0]];
  for (let ring = 1; points.length < count; ring += 1) {
    for (let side = 0; side < 6; side += 1) {
      for (let step = 0; step < ring; step += 1) {
        const a0 = (Math.PI / 3) * side;
        const a1 = (Math.PI / 3) * (side + 1);
        const x = ring * Math.cos(a0) + (step / ring) * ring * (Math.cos(a1) - Math.cos(a0));
        const y = ring * Math.sin(a0) + (step / ring) * ring * (Math.sin(a1) - Math.sin(a0));
        points.push([x * spacing, y * spacing]);
        if (points.length >= count) break;
      }
      if (points.length >= count) break;
    }
  }
  return points;
}

function random(seed) {
  let s = seed;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

// ---------------------------------------------------------------------------
// Product compositions (each returns a THREE.Group centred at the origin)
// ---------------------------------------------------------------------------

export const PRODUCTS = {
  rebar() {
    const group = new THREE.Group();
    const geometry = rebarGeometry(4.6, 0.05);
    const material = MATERIALS.rebar();
    const rnd = random(11);
    for (const [x, y] of hexPack(19, 0.108)) {
      const bar = new THREE.Mesh(geometry, material);
      bar.position.set(x, y, (rnd() - 0.5) * 0.5);
      bar.rotation.z = rnd() * Math.PI;
      group.add(bar);
    }
    const tieMaterial = MATERIALS.dark();
    for (const z of [-1.4, 0.2, 1.6]) {
      const tie = new THREE.Mesh(new THREE.TorusGeometry(0.29, 0.01, 8, 48), tieMaterial);
      tie.position.z = z;
      group.add(tie);
    }
    return group;
  },
  beam() {
    const group = new THREE.Group();
    const geometry = iBeamGeometry(4.4, 0.46, 0.24);
    const material = MATERIALS.mill();
    const layout = [[-0.25, 0, 0.1], [0, 0, -0.15], [0.25, 0, 0.3], [-0.125, 0.47, -0.35], [0.125, 0.47, 0.05]];
    for (const [x, y, z] of layout) {
      const beam = new THREE.Mesh(geometry, material);
      beam.position.set(x, y, z);
      group.add(beam);
    }
    return group;
  },
  'steel-sheet'() {
    const group = new THREE.Group();
    const material = MATERIALS.mill();
    const rnd = random(5);
    for (let i = 0; i < 9; i += 1) {
      const plate = new THREE.Mesh(new THREE.BoxGeometry(2.6, 0.035, 1.6), material);
      plate.position.set((rnd() - 0.5) * 0.06, i * 0.04, (rnd() - 0.5) * 0.06);
      plate.rotation.y = (rnd() - 0.5) * 0.03;
      group.add(plate);
    }
    const coilShape = new THREE.Shape();
    coilShape.absarc(0, 0, 0.78, 0, Math.PI * 2, false);
    const hole = new THREE.Path();
    hole.absarc(0, 0, 0.3, 0, Math.PI * 2, true);
    coilShape.holes.push(hole);
    const coil = new THREE.Mesh(extrude(coilShape, 0.9, 0.02), MATERIALS.galvanized());
    coil.position.set(0.6, 0.78 + 0.36, -0.1);
    coil.rotation.y = Math.PI / 2.4;
    group.add(coil);
    group.position.y = -0.5;
    return group;
  },
  pipe() {
    const group = new THREE.Group();
    const geometry = tubeGeometry(4.4, 0.12, 0.014);
    const material = MATERIALS.bright();
    const rnd = random(7);
    for (const [x, y] of hexPack(14, 0.245)) {
      const tube = new THREE.Mesh(geometry, material);
      tube.position.set(x, y, (rnd() - 0.5) * 0.7);
      group.add(tube);
    }
    return group;
  },
  profiles() {
    const group = new THREE.Group();
    const material = MATERIALS.dark();
    const geometry = boxSectionGeometry(4.4, 0.24, 0.24);
    const rnd = random(3);
    for (let row = 0; row < 3; row += 1) {
      for (let col = 0; col < 4 - row; col += 1) {
        const box = new THREE.Mesh(geometry, material);
        box.position.set((col - (3 - row) / 2) * 0.26, row * 0.25, (rnd() - 0.5) * 0.5);
        group.add(box);
      }
    }
    return group;
  },
  'angles-channels'() {
    const group = new THREE.Group();
    const angle = angleGeometry(4.4, 0.26, 0.032);
    const channel = channelGeometry(4.4, 0.32, 0.13, 0.03);
    const material = MATERIALS.mill();
    for (let i = 0; i < 3; i += 1) {
      const mesh = new THREE.Mesh(angle, material);
      mesh.position.set(-0.75 + i * 0.29, 0, i * 0.12);
      group.add(mesh);
    }
    for (let i = 0; i < 2; i += 1) {
      const mesh = new THREE.Mesh(channel, MATERIALS.dark());
      mesh.position.set(0.25 + i * 0.36, 0, -0.2 + i * 0.15);
      mesh.rotation.z = Math.PI / 2;
      mesh.position.x += 0.32;
      group.add(mesh);
    }
    group.position.set(0, -0.15, 0);
    return group;
  },
  'wire-products'() {
    const group = new THREE.Group();
    const turns = 34;
    const points = [];
    for (let i = 0; i <= turns * 64; i += 1) {
      const t = i / 64;
      const angle = t * Math.PI * 2;
      const layer = Math.floor(t) % 3;
      const radius = 0.78 + layer * 0.035 + Math.sin(t * 7.1) * 0.01;
      points.push(new THREE.Vector3(Math.cos(angle) * radius, (t / turns) * 0.9 - 0.45, Math.sin(angle) * radius));
    }
    const curve = new THREE.CatmullRomCurve3(points);
    const wire = new THREE.Mesh(new THREE.TubeGeometry(curve, turns * 64, 0.018, 6, false), MATERIALS.dark());
    group.add(wire);
    const mesh = new THREE.Group();
    const barMaterial = MATERIALS.rebar();
    for (let i = -4; i <= 4; i += 1) {
      for (const dir of [0, 1]) {
        const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 2.2, 8), barMaterial);
        bar.rotation.z = Math.PI / 2;
        if (dir) bar.rotation.y = Math.PI / 2;
        bar.position[dir ? 'x' : 'z'] = i * 0.24;
        bar.position.y = dir * 0.025;
        mesh.add(bar);
      }
    }
    mesh.rotation.x = -0.15;
    mesh.position.set(0, -0.62, 0);
    group.add(mesh);
    return group;
  },
  billets() {
    const group = new THREE.Group();
    const s = new THREE.Shape();
    const w = 0.15;
    s.moveTo(-w, -w);
    s.lineTo(w, -w);
    s.lineTo(w, w);
    s.lineTo(-w, w);
    s.closePath();
    const geometry = extrude(s, 3.6, 0.03);
    const material = MATERIALS.dark();
    const rnd = random(13);
    for (let row = 0; row < 3; row += 1) {
      for (let col = 0; col < 4; col += 1) {
        const billet = new THREE.Mesh(geometry, material);
        billet.position.set((col - 1.5) * 0.36, row * 0.36, (rnd() - 0.5) * 0.4);
        group.add(billet);
      }
    }
    const hot = new THREE.Mesh(geometry, MATERIALS.ember());
    hot.position.set(0, 3 * 0.36, 0.3);
    group.add(hot);
    group.position.y = -0.4;
    return group;
  },
  'raw-materials'() {
    const group = new THREE.Group();
    const rnd = random(17);
    const geometry = new THREE.IcosahedronGeometry(0.07, 2);
    const material = MATERIALS.pellet();
    const instances = new THREE.InstancedMesh(geometry, material, 900);
    const matrix = new THREE.Matrix4();
    let n = 0;
    while (n < 900) {
      const angle = rnd() * Math.PI * 2;
      const radius = Math.sqrt(rnd()) * 1.5;
      const height = Math.max(0, 0.95 * (1 - radius / 1.5)) * rnd();
      const scale = 0.8 + rnd() * 0.5;
      matrix.compose(
        new THREE.Vector3(Math.cos(angle) * radius, height, Math.sin(angle) * radius),
        new THREE.Quaternion().setFromEuler(new THREE.Euler(rnd() * 3, rnd() * 3, 0)),
        new THREE.Vector3(scale, scale * (0.9 + rnd() * 0.2), scale),
      );
      instances.setMatrixAt(n, matrix);
      n += 1;
    }
    group.add(instances);
    group.position.y = -0.35;
    return group;
  },
  ferroalloy() {
    const group = new THREE.Group();
    const rnd = random(23);
    const material = MATERIALS.alloy();
    for (let i = 0; i < 26; i += 1) {
      const geometry = new THREE.IcosahedronGeometry(0.16 + rnd() * 0.12, 0);
      const position = geometry.attributes.position;
      for (let v = 0; v < position.count; v += 1) {
        position.setXYZ(v, position.getX(v) * (0.7 + rnd() * 0.6), position.getY(v) * (0.6 + rnd() * 0.6), position.getZ(v) * (0.7 + rnd() * 0.6));
      }
      geometry.computeVertexNormals();
      const chunk = new THREE.Mesh(geometry, material);
      const angle = rnd() * Math.PI * 2;
      const radius = Math.sqrt(rnd()) * 1.1;
      chunk.position.set(Math.cos(angle) * radius, (1 - radius / 1.1) * 0.5 * rnd(), Math.sin(angle) * radius);
      chunk.rotation.set(rnd() * 3, rnd() * 3, rnd() * 3);
      group.add(chunk);
    }
    group.position.y = -0.2;
    return group;
  },
};

// ---------------------------------------------------------------------------
// Studio
// ---------------------------------------------------------------------------

export function createRenderer(canvas, { alpha = true, antialias = true } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, alpha, antialias, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  return renderer;
}

export function createStudio(renderer, { warm = 0xff7a2e, cool = 0x8fb7ff, floor = true } = {}) {
  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.03).texture;
  scene.environmentIntensity = 0.95;

  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(3.5, 5, 4);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.left = key.shadow.camera.bottom = -4;
  key.shadow.camera.right = key.shadow.camera.top = 4;
  key.shadow.radius = 6;
  key.shadow.bias = -0.0004;
  scene.add(key);

  const rimWarm = new THREE.PointLight(warm, 28, 14, 1.6);
  rimWarm.position.set(-4, 1.4, -2.5);
  scene.add(rimWarm);
  const rimCool = new THREE.PointLight(cool, 14, 14, 1.6);
  rimCool.position.set(4, 2.2, -3.5);
  scene.add(rimCool);
  scene.add(new THREE.HemisphereLight(0xdfe7f2, 0x2a2420, 0.35));

  if (floor) {
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(20, 20), new THREE.ShadowMaterial({ opacity: 0.32 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.62;
    ground.receiveShadow = true;
    scene.add(ground);
  }
  return scene;
}

export function enableShadows(object) {
  object.traverse((child) => {
    if (child.isMesh) {
      child.castShadow = true;
      child.receiveShadow = true;
    }
  });
  return object;
}

export function fitToGround(object, groundY = -0.6) {
  const box = new THREE.Box3().setFromObject(object);
  object.position.y += groundY - box.min.y;
  return object;
}

export { THREE };
