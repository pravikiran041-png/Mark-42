import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

export interface FileNodeData {
  name: string;
  path: string;
  is_dir: boolean;
}

export interface FileSceneApi {
  controls: OrbitControls;
  resize(): void;
  animate(): void;
  dispose(): void;
  updateFiles(files: FileNodeData[]): void;
  updateHandPointer(x: number, y: number, isPinching: boolean): void;
  onFileDeleted(callback: (path: string) => void): void;
}

export function createFileScene(
  container: HTMLDivElement,
  onDeletedCallback: (path: string) => void
): FileSceneApi {
  const W = container.clientWidth;
  const H = container.clientHeight;

  // Scene & Camera
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x00060a, 0.05);

  const camera = new THREE.PerspectiveCamera(55, W / H, 0.1, 100);
  camera.position.set(0, 0, 7);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(W, H);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;
  controls.enablePan = false;
  controls.minDistance = 3;
  controls.maxDistance = 15;

  // Lighting
  const ambientLight = new THREE.AmbientLight(0xffaa30, 0.25);
  scene.add(ambientLight);

  const dirLight = new THREE.DirectionalLight(0xffcc66, 0.8);
  dirLight.position.set(5, 5, 5);
  scene.add(dirLight);

  const fileGroup = new THREE.Group();
  scene.add(fileGroup);

  // 3D Trash Bin Model (Glowing cylinder wireframe)
  const binGroup = new THREE.Group();
  binGroup.position.set(3, -2, 0); // Position bottom-right
  scene.add(binGroup);

  const binGeo = new THREE.CylinderGeometry(0.6, 0.5, 1.2, 8, 3, true);
  const binMat = new THREE.MeshBasicMaterial({
    color: 0xff3355,
    wireframe: true,
    transparent: true,
    opacity: 0.4
  });
  const binMesh = new THREE.Mesh(binGeo, binMat);
  binGroup.add(binMesh);

  // Glow base ring
  const ringGeo = new THREE.RingGeometry(0.5, 0.7, 8);
  const ringMat = new THREE.MeshBasicMaterial({ color: 0xff3355, side: THREE.DoubleSide, transparent: true, opacity: 0.15 });
  const ring = new THREE.Mesh(ringGeo, ringMat);
  ring.rotation.x = Math.PI / 2;
  ring.position.y = -0.6;
  binGroup.add(ring);

  // Floating Trash Bin Label Sprite
  const canvasBin = document.createElement("canvas");
  canvasBin.width = 128;
  canvasBin.height = 32;
  const ctxBin = canvasBin.getContext("2d")!;
  ctxBin.font = "bold 20px 'Courier New'";
  ctxBin.fillStyle = "#ff3355";
  ctxBin.textAlign = "center";
  ctxBin.fillText("TRASH BIN", 64, 24);
  const binTex = new THREE.CanvasTexture(canvasBin);
  const binLabelMat = new THREE.SpriteMaterial({ map: binTex, transparent: true });
  const binLabel = new THREE.Sprite(binLabelMat);
  binLabel.position.y = 0.9;
  binLabel.scale.set(1.4, 0.35, 1);
  binGroup.add(binLabel);

  // Hand pointer cursor mesh
  const cursorGeo = new THREE.SphereGeometry(0.12, 8, 8);
  const cursorMat = new THREE.MeshBasicMaterial({ color: 0x00ff88, transparent: true, opacity: 0.8 });
  const cursorMesh = new THREE.Mesh(cursorGeo, cursorMat);
  cursorMesh.visible = false;
  scene.add(cursorMesh);

  // Local state
  let fileObjects: THREE.Object3D[] = [];
  let grabbedObject: THREE.Object3D | null = null;
  let handX = 0, handY = 0;
  let isPinching = false;
  let wasPinching = false;
  let deleteCallback = onDeletedCallback;

  // Build Canvas Text texture helper
  function createTextSprite(text: string, colorStr: string): THREE.Sprite {
    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = 64;
    const ctx = canvas.getContext("2d")!;
    
    // Draw background panel
    ctx.fillStyle = "rgba(1, 15, 24, 0.8)";
    ctx.fillRect(4, 4, 248, 56);
    ctx.strokeStyle = colorStr;
    ctx.lineWidth = 2;
    ctx.strokeRect(4, 4, 248, 56);
    
    ctx.font = "bold 15px 'Courier New'";
    ctx.fillStyle = colorStr;
    ctx.textAlign = "center";
    ctx.fillText(text.length > 20 ? text.substring(0, 17) + "..." : text, 128, 36);
    
    const texture = new THREE.CanvasTexture(canvas);
    const spriteMat = new THREE.SpriteMaterial({ map: texture, transparent: true });
    const sprite = new THREE.Sprite(spriteMat);
    sprite.scale.set(2.0, 0.5, 1);
    return sprite;
  }

  function updateFiles(files: FileNodeData[]) {
    // Clean up existing meshes
    fileObjects.forEach(obj => fileGroup.remove(obj));
    fileObjects = [];
    grabbedObject = null;

    // Arrange in a neat 3D grid layout
    const cols = 4;
    const spacingX = 2.4;
    const spacingY = 1.2;
    const startX = -((cols - 1) * spacingX) / 2;
    const startY = 1.8;

    files.forEach((file, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);

      const color = file.is_dir ? "#00d4ff" : "#ffaa30";
      const sprite = createTextSprite(file.name, color);
      
      const fileContainer = new THREE.Group();
      fileContainer.position.set(startX + col * spacingX, startY - row * spacingY, 0);
      fileContainer.add(sprite);

      // Store home position for physics recall
      fileContainer.userData = {
        path: file.path,
        homeX: fileContainer.position.x,
        homeY: fileContainer.position.y,
        homeZ: fileContainer.position.z,
        isGrabbed: false
      };

      fileGroup.add(fileContainer);
      fileObjects.push(fileContainer);
    });
  }

  function updateHandPointer(x: number, y: number, pinching: boolean) {
    handX = x;
    handY = y;
    isPinching = pinching;
    cursorMesh.visible = true;

    // Project screen coordinates to 3D space near the focal plane
    const vector = new THREE.Vector3(
      (x * 2) - 1,
      -(y * 2) + 1,
      0.5
    );
    vector.unproject(camera);
    const dir = vector.sub(camera.position).normalize();
    const distance = -camera.position.z / dir.z; // project on z=0 plane
    const pos = camera.position.clone().add(dir.multiplyScalar(distance));
    cursorMesh.position.copy(pos);
    cursorMesh.position.z = 0.2; // slightly elevated

    // Change color based on pinch state
    (cursorMesh.material as THREE.MeshBasicMaterial).color.setHex(pinching ? 0xffaa30 : 0x00ff88);
  }

  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();

  function animate() {
    controls.update();

    // Check interaction logic if pointer is active
    if (cursorMesh.visible) {
      mouse.x = (handX * 2) - 1;
      mouse.y = -(handY * 2) + 1;
      raycaster.setFromCamera(mouse, camera);

      if (isPinching && !wasPinching) {
        // Look for intersections to grab
        const intersects = raycaster.intersectObjects(fileGroup.children, true);
        if (intersects.length > 0) {
          // Find root container in fileGroup
          let rootObj: THREE.Object3D | null = intersects[0].object;
          while (rootObj && rootObj.parent !== fileGroup) {
            rootObj = rootObj.parent;
          }
          if (rootObj) {
            grabbedObject = rootObj;
            grabbedObject.userData.isGrabbed = true;
          }
        }
      }

      // Drag action
      if (isPinching && grabbedObject) {
        grabbedObject.position.copy(cursorMesh.position);
        grabbedObject.position.z = 0; // lock to 2D workspace plane
      }

      // Drop action
      if (!isPinching && wasPinching && grabbedObject) {
        grabbedObject.userData.isGrabbed = false;
        
        // Distance check from Trash Bin
        const dist = grabbedObject.position.distanceTo(binGroup.position);
        if (dist < 1.0) {
          // Trigger delete callback
          const path = grabbedObject.userData.path;
          deleteCallback(path);
          
          // Shrink & Fade Out Animation
          const objToDel = grabbedObject;
          let scale = 1.0;
          const shrinkInterval = setInterval(() => {
            scale -= 0.1;
            if (scale <= 0) {
              clearInterval(shrinkInterval);
              fileGroup.remove(objToDel);
            } else {
              objToDel.scale.set(scale, scale, scale);
            }
          }, 20);
        }
        grabbedObject = null;
      }
    }

    // Spring Physics / Animate elements back home when released
    fileObjects.forEach(obj => {
      if (!obj.userData.isGrabbed) {
        const homeX = obj.userData.homeX;
        const homeY = obj.userData.homeY;
        const homeZ = obj.userData.homeZ;
        
        // Linear interpolation to spring back to original position
        obj.position.x += (homeX - obj.position.x) * 0.1;
        obj.position.y += (homeY - obj.position.y) * 0.1;
        obj.position.z += (homeZ - obj.position.z) * 0.1;
      }
    });

    // Spin trash bin cylinder slightly
    binMesh.rotation.y += 0.01;

    wasPinching = isPinching;
    renderer.render(scene, camera);
  }

  function resize() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }

  function dispose() {
    renderer.dispose();
    container.removeChild(renderer.domElement);
  }

  return {
    controls,
    resize,
    animate,
    dispose,
    updateFiles,
    updateHandPointer,
    onFileDeleted: (cb) => { deleteCallback = cb; }
  };
}
