import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { X, RotateCcw, Loader2, AlertTriangle } from 'lucide-react';
import { takeoffAPI } from '../services/api';
import { getRoomColor } from '../mock/mockAI';

// Interactive 3D — memory/TOGAL_PARITY_REAUDIT.md #19 ("demo value" per
// Togal's own positioning, not a measurement tool). Extrudes the SAME real
// PostGIS geometry (GET /drawings/{id}/detections, already built for the
// PostGIS-first-class guardrail) that the 2D overlay is grounded in — no
// separate 3D-only data source, so the 3D view can never show something
// the 2D takeoff doesn't. No AI/GPU inference here: this is pure
// client-side WebGL rendering of already-computed geometry, so it doesn't
// touch CLAUDE.md guardrail #1 (no inference on Vercel) at all.

const REFERENCE_DPI = 300; // matches ai/preprocessing.py's TARGET_DPI / scale_routes.py's REFERENCE_DPI
const DEFAULT_SCALE_RATIO = 48; // 1/4" = 1'-0" — used only when the drawing has no calibrated scale yet
const WALL_HEIGHT_FT = 9; // matches the "9ft walls" convention already used in handoff_engine.py's CSI seed catalog
const WALL_THICKNESS_FT = 0.5;

const MARKER_COLORS = { Door: '#10b981', Window: '#3b82f6' };

function pixelsToFeet(px, scaleRatio) {
  // Same formula as ai/preprocessing.py's pixels_to_feet(): inches_per_pixel * scale_ratio / 12
  return (px * scaleRatio) / (REFERENCE_DPI * 12);
}

function polygonCentroid(coords) {
  let x = 0, y = 0;
  const pts = coords[0] || [];
  const n = Math.max(pts.length - 1, 1); // last point repeats the first for a closed ring
  for (let i = 0; i < n; i++) { x += pts[i][0]; y += pts[i][1]; }
  return [x / n, y / n];
}

export default function Drawing3DView({ drawingId, drawingName, scaleRatio, onClose }) {
  const containerRef = useRef(null);
  const sceneRef = useRef(null); // { renderer, controls, camera, frameId }
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);
  const usingDefaultScale = !scaleRatio;

  useEffect(() => {
    let cancelled = false;

    async function build() {
      setLoading(true);
      setError(null);
      try {
        const res = await takeoffAPI.getDetections(drawingId);
        if (cancelled) return;
        const detections = res.data || [];
        if (detections.length === 0) {
          setError('No AI/manual detections persisted for this drawing yet — run a takeoff first.');
          setLoading(false);
          return;
        }
        mountScene(detections);
      } catch (err) {
        if (!cancelled) {
          setError(err.response?.data?.detail || 'Failed to load geometry for 3D view');
          setLoading(false);
        }
      }
    }

    function mountScene(detections) {
      const effectiveScale = scaleRatio || DEFAULT_SCALE_RATIO;
      const rooms = [];
      const walls = [];
      const markers = [];

      for (const d of detections) {
        if (d.annotation_type === 'area' && d.geometry?.type === 'Polygon') {
          rooms.push(d);
        } else if (d.annotation_type === 'line' && d.geometry?.type === 'LineString') {
          walls.push(d);
        } else if (d.annotation_type === 'count' && d.geometry?.type === 'Polygon') {
          markers.push(d);
        }
      }

      const container = containerRef.current;
      if (!container) return;
      const width = container.clientWidth, height = container.clientHeight;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color('#1e293b');

      const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 5000);
      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      container.innerHTML = '';
      container.appendChild(renderer.domElement);

      scene.add(new THREE.AmbientLight('#ffffff', 0.6));
      const dirLight = new THREE.DirectionalLight('#ffffff', 0.9);
      dirLight.position.set(80, 120, 60);
      scene.add(dirLight);

      // Plan-space pixel Y grows downward; map it onto the scene's Z axis
      // (negated) so the floor plan reads right-side-up when viewed from above.
      const toScene = (px, py) => [pixelsToFeet(px, effectiveScale), -pixelsToFeet(py, effectiveScale)];

      let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
      const trackBounds = (x, z) => {
        minX = Math.min(minX, x); maxX = Math.max(maxX, x);
        minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z);
      };

      for (const room of rooms) {
        const ring = room.geometry.coordinates[0];
        const shape = new THREE.Shape();
        ring.forEach(([px, py], i) => {
          const [x, z] = toScene(px, py);
          trackBounds(x, z);
          if (i === 0) shape.moveTo(x, z); else shape.lineTo(x, z);
        });
        const geom = new THREE.ExtrudeGeometry(shape, { depth: 0.3, bevelEnabled: false });
        geom.rotateX(-Math.PI / 2);
        const color = getRoomColor(room.class_label);
        const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.85 }));
        scene.add(mesh);

        const edges = new THREE.EdgesGeometry(geom);
        scene.add(new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: '#0f172a' })));
      }

      for (const wall of walls) {
        const pts = wall.geometry.coordinates;
        const isExterior = wall.class_label?.startsWith('exterior');
        const color = isExterior ? '#475569' : '#cbd5e1';
        for (let i = 0; i < pts.length - 1; i++) {
          const [x1, z1] = toScene(pts[i][0], pts[i][1]);
          const [x2, z2] = toScene(pts[i + 1][0], pts[i + 1][1]);
          trackBounds(x1, z1); trackBounds(x2, z2);
          const length = Math.hypot(x2 - x1, z2 - z1);
          if (length < 0.01) continue;
          const angle = Math.atan2(z2 - z1, x2 - x1);
          const box = new THREE.BoxGeometry(length, WALL_HEIGHT_FT, WALL_THICKNESS_FT);
          const mesh = new THREE.Mesh(box, new THREE.MeshStandardMaterial({ color }));
          mesh.position.set((x1 + x2) / 2, WALL_HEIGHT_FT / 2, (z1 + z2) / 2);
          mesh.rotation.y = -angle;
          scene.add(mesh);
        }
      }

      for (const marker of markers) {
        const [px, py] = polygonCentroid(marker.geometry.coordinates);
        const [x, z] = toScene(px, py);
        const color = MARKER_COLORS[marker.class_label] || '#f59e0b';
        const mesh = new THREE.Mesh(
          new THREE.SphereGeometry(0.6, 12, 12),
          new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.3 }),
        );
        mesh.position.set(x, 3, z);
        scene.add(mesh);
      }

      const centerX = (minX + maxX) / 2 || 0;
      const centerZ = (minZ + maxZ) / 2 || 0;
      const span = Math.max(maxX - minX, maxZ - minZ, 10);

      const ground = new THREE.Mesh(
        new THREE.PlaneGeometry(span * 3, span * 3),
        new THREE.MeshStandardMaterial({ color: '#0f172a' }),
      );
      ground.rotation.x = -Math.PI / 2;
      ground.position.set(centerX, -0.05, centerZ);
      scene.add(ground);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.target.set(centerX, 0, centerZ);
      const resetCamera = () => {
        camera.position.set(centerX + span * 0.7, span * 0.9, centerZ + span * 0.9);
        controls.target.set(centerX, 0, centerZ);
        controls.update();
      };
      resetCamera();
      controls.enableDamping = true;

      let frameId;
      const animate = () => {
        controls.update();
        renderer.render(scene, camera);
        frameId = requestAnimationFrame(animate);
      };
      animate();

      sceneRef.current = { renderer, controls, resetCamera, frameId: () => frameId };
      setStats({ rooms: rooms.length, walls: walls.length, markers: markers.length });
      setLoading(false);
    }

    build();

    return () => {
      cancelled = true;
      if (sceneRef.current) {
        cancelAnimationFrame(sceneRef.current.frameId());
        sceneRef.current.controls.dispose();
        sceneRef.current.renderer.dispose();
        sceneRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawingId, scaleRatio]);

  return (
    <div className="fixed inset-0 z-50 bg-slate-950 flex flex-col">
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800 bg-slate-900">
        <div>
          <h3 className="text-sm font-semibold text-white">3D view — {drawingName}</h3>
          {usingDefaultScale && !loading && !error && (
            <p className="text-[11px] text-amber-400 flex items-center gap-1 mt-0.5">
              <AlertTriangle className="w-3 h-3" /> Scale not calibrated — showing approximate proportions (assumed 1/4" = 1'-0").
            </p>
          )}
          {stats && !loading && (
            <p className="text-[11px] text-slate-400 mt-0.5">{stats.rooms} rooms · {stats.walls} wall segments · {stats.markers} doors/windows</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => sceneRef.current?.resetCamera()}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-white"
          >
            <RotateCcw className="w-3.5 h-3.5" /> Reset view
          </button>
          <button onClick={onClose} className="w-8 h-8 rounded-lg hover:bg-slate-800 flex items-center justify-center text-slate-300">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 relative">
        {/* Always laid out (never display:none) — mountScene() reads
            container.clientWidth/clientHeight synchronously right after the
            fetch resolves, while `loading` is still true; a hidden
            container would measure 0x0 at exactly that moment, since React
            hasn't re-rendered with loading=false yet. Loading/error states
            render as overlays on top instead. */}
        <div ref={containerRef} className="absolute inset-0" />
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center text-slate-400 gap-2 bg-slate-950">
            <Loader2 className="w-5 h-5 animate-spin" /> Loading geometry…
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center text-center px-6 bg-slate-950">
            <p className="text-sm text-rose-400 max-w-sm">{error}</p>
          </div>
        )}
      </div>
    </div>
  );
}
