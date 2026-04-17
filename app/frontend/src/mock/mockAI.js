// Simulated AI service: looks and behaves like a real async API
// Produces structured, realistic detection JSON for the canvas viewer.

const rand = (min, max) => Math.round((Math.random() * (max - min) + min) * 100) / 100;
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

const ROOM_TYPES = ['Living', 'Master Bedroom', 'Bedroom', 'Kitchen', 'Bathroom', 'Dining', 'Office', 'Hallway', 'Closet', 'Utility', 'Laundry', 'Lobby'];
const ROOM_COLORS = {
  'Living': '#818cf8',
  'Master Bedroom': '#a78bfa',
  'Bedroom': '#c4b5fd',
  'Kitchen': '#fbbf24',
  'Bathroom': '#22d3ee',
  'Dining': '#f472b6',
  'Office': '#34d399',
  'Hallway': '#94a3b8',
  'Closet': '#cbd5e1',
  'Utility': '#fb7185',
  'Laundry': '#60a5fa',
  'Lobby': '#fcd34d',
};

// Fixed, curated sample so canvas layout always looks sensible
export const SAMPLE_DETECTION = {
  id: 'detection_sample_001',
  sheet: 'A-101 — Level 12 Floor Plan',
  scale: '1/8" = 1\'-0"',
  processingTimeMs: 1420,
  summary: {
    rooms: 9,
    doors: 14,
    windows: 18,
    walls: 42,
    totalArea: 4280,
  },
  rooms: [
    { id: 'r1', label: 'Living', bbox: [60, 60, 260, 200], area: 420, confidence: 0.98 },
    { id: 'r2', label: 'Kitchen', bbox: [320, 60, 500, 200], area: 320, confidence: 0.97 },
    { id: 'r3', label: 'Dining', bbox: [60, 220, 260, 360], area: 310, confidence: 0.95 },
    { id: 'r4', label: 'Hallway', bbox: [260, 220, 340, 440], area: 180, confidence: 0.96 },
    { id: 'r5', label: 'Master Bedroom', bbox: [340, 220, 560, 440], area: 510, confidence: 0.97 },
    { id: 'r6', label: 'Bathroom', bbox: [560, 220, 720, 340], area: 210, confidence: 0.94 },
    { id: 'r7', label: 'Closet', bbox: [560, 340, 720, 440], area: 160, confidence: 0.92 },
    { id: 'r8', label: 'Bedroom', bbox: [60, 380, 260, 520], area: 290, confidence: 0.95 },
    { id: 'r9', label: 'Office', bbox: [340, 460, 560, 600], area: 380, confidence: 0.93 },
  ],
  doors: [
    { id: 'd1', x: 260, y: 130, width: 28, rotation: 0, confidence: 0.97 },
    { id: 'd2', x: 320, y: 130, width: 28, rotation: 0, confidence: 0.96 },
    { id: 'd3', x: 340, y: 300, width: 28, rotation: 0, confidence: 0.94 },
    { id: 'd4', x: 560, y: 280, width: 28, rotation: 0, confidence: 0.96 },
    { id: 'd5', x: 560, y: 380, width: 28, rotation: 0, confidence: 0.92 },
    { id: 'd6', x: 260, y: 440, width: 28, rotation: 90, confidence: 0.95 },
    { id: 'd7', x: 340, y: 540, width: 28, rotation: 0, confidence: 0.93 },
    { id: 'd8', x: 140, y: 220, width: 28, rotation: 90, confidence: 0.97 },
    { id: 'd9', x: 440, y: 220, width: 28, rotation: 90, confidence: 0.95 },
    { id: 'd10', x: 460, y: 460, width: 28, rotation: 90, confidence: 0.94 },
    { id: 'd11', x: 180, y: 380, width: 28, rotation: 90, confidence: 0.93 },
    { id: 'd12', x: 580, y: 340, width: 28, rotation: 90, confidence: 0.91 },
    { id: 'd13', x: 120, y: 520, width: 28, rotation: 90, confidence: 0.9 },
    { id: 'd14', x: 400, y: 600, width: 28, rotation: 90, confidence: 0.92 },
  ],
  windows: [
    { id: 'w1', x: 100, y: 60, width: 50, confidence: 0.97 },
    { id: 'w2', x: 180, y: 60, width: 50, confidence: 0.96 },
    { id: 'w3', x: 380, y: 60, width: 50, confidence: 0.96 },
    { id: 'w4', x: 450, y: 60, width: 50, confidence: 0.95 },
    { id: 'w5', x: 60, y: 280, width: 50, rotation: 90, confidence: 0.94 },
    { id: 'w6', x: 60, y: 440, width: 50, rotation: 90, confidence: 0.93 },
    { id: 'w7', x: 400, y: 600, width: 50, confidence: 0.95 },
    { id: 'w8', x: 480, y: 600, width: 50, confidence: 0.94 },
    { id: 'w9', x: 720, y: 260, width: 50, rotation: 90, confidence: 0.92 },
    { id: 'w10', x: 720, y: 380, width: 50, rotation: 90, confidence: 0.91 },
    { id: 'w11', x: 380, y: 440, width: 50, confidence: 0.93 },
    { id: 'w12', x: 140, y: 520, width: 50, confidence: 0.91 },
    { id: 'w13', x: 220, y: 520, width: 50, confidence: 0.91 },
    { id: 'w14', x: 580, y: 600, width: 50, confidence: 0.9 },
    { id: 'w15', x: 660, y: 600, width: 50, confidence: 0.9 },
    { id: 'w16', x: 60, y: 120, width: 50, rotation: 90, confidence: 0.93 },
    { id: 'w17', x: 500, y: 460, width: 50, confidence: 0.92 },
    { id: 'w18', x: 300, y: 600, width: 50, confidence: 0.91 },
  ],
  quantities: [
    { trade: 'Drywall', item: 'Interior partition linear feet', quantity: 312, unit: 'lf' },
    { trade: 'Drywall', item: 'Gypsum board surface area', quantity: 2180, unit: 'sf' },
    { trade: 'Painting', item: 'Paintable wall area', quantity: 2140, unit: 'sf' },
    { trade: 'Painting', item: 'Ceiling paintable area', quantity: 1560, unit: 'sf' },
    { trade: 'Flooring', item: 'Carpet — bedrooms', quantity: 800, unit: 'sf' },
    { trade: 'Flooring', item: 'Tile — wet areas', quantity: 210, unit: 'sf' },
    { trade: 'Flooring', item: 'Hardwood — common', quantity: 1050, unit: 'sf' },
    { trade: 'Doors', item: 'Interior doors 3\'-0"', quantity: 12, unit: 'ea' },
    { trade: 'Doors', item: 'Closet bi-fold doors', quantity: 2, unit: 'ea' },
    { trade: 'Windows', item: 'Double-hung 4\'-0" x 5\'-0"', quantity: 14, unit: 'ea' },
    { trade: 'Windows', item: 'Fixed transom 2\'-0" x 3\'-0"', quantity: 4, unit: 'ea' },
    { trade: 'Electrical', item: 'Standard duplex outlets', quantity: 46, unit: 'ea' },
    { trade: 'Electrical', item: 'Light fixtures', quantity: 32, unit: 'ea' },
    { trade: 'Plumbing', item: 'Plumbing fixtures', quantity: 9, unit: 'ea' },
  ],
};

export function getRoomColor(label) {
  return ROOM_COLORS[label] || '#818cf8';
}

// Simulated async AI call with progress events
export async function runTakeoffAI({ onProgress, seed }) {
  const stages = [
    { msg: 'Initializing AI scanner...', delay: 300, pct: 8 },
    { msg: 'Parsing drawing geometry...', delay: 500, pct: 18 },
    { msg: 'Detecting auto-scale reference...', delay: 400, pct: 32 },
    { msg: 'Running room segmentation (AI)...', delay: 700, pct: 58 },
    { msg: 'Classifying doors, windows & fixtures...', delay: 550, pct: 80 },
    { msg: 'Detecting wall boundaries...', delay: 350, pct: 90 },
    { msg: 'Computing quantities per trade...', delay: 400, pct: 95 },
    { msg: 'Finalizing report...', delay: 250, pct: 100 },
  ];

  for (const s of stages) {
    await new Promise((r) => setTimeout(r, s.delay));
    if (onProgress) onProgress(s);
  }
  // Slightly randomize confidence values to feel alive

// Randomize confidence values and add slight variation to detection counts
  const out = JSON.parse(JSON.stringify(SAMPLE_DETECTION));

    // Add slight randomness to confidence scores
  out.rooms = out.rooms.map((r) => ({ ...r, confidence: Math.min(0.99, r.confidence + rand(-0.02, 0.02)) }));
  out.doors = out.doors.map((d) => ({ ...d, confidence: Math.min(0.99, d.confidence + rand(-0.03, 0.02)) }));
  out.windows = out.windows.map((w) => ({ ...w, confidence: Math.min(0.99, w.confidence + rand(-0.03, 0.02)) }));
  
   // Randomize processing time
  out.processingTimeMs = 1200 + Math.floor(rand(200, 800));

  // Add staggered reveal delays for animation (used by canvas)
  out.rooms = out.rooms.map((r, i) => ({ ...r, revealDelay: i * 80 }));
  out.doors = out.doors.map((d, i) => ({ ...d, revealDelay: i * 40 }));
  out.windows = out.windows.map((w, i) => ({ ...w, revealDelay: i * 40 }));
  
  return out;
}

export async function askTakeoffChat(question) {
  await new Promise((r) => setTimeout(r, 900));
  const canned = [
    { match: /room|rooms/i, answer: 'I found 9 rooms across this sheet totaling 4,280 sf. The largest is the Master Bedroom at 510 sf. Would you like a breakdown by room type?' },
    { match: /door/i, answer: 'There are 14 doors on this sheet. 12 standard interior 3\'-0" and 2 bi-fold closet doors. Confidence averages 94%.' },
    { match: /window/i, answer: 'I detected 18 windows. 14 are double-hung 4\'-0" × 5\'-0" and 4 are fixed transoms. Total glazing area is ~312 sf.' },
    { match: /paint|surface/i, answer: 'Paintable wall area is 2,140 sf and ceiling paint is 1,560 sf — total ~3,700 sf. I filtered out tile wet-walls automatically.' },
    { match: /scope|rfp/i, answer: 'Drafting scope now: interior partitions, drywall and paint, interior doors, windows, flooring, fixtures and finishes. Want me to export to Excel?' },
    { match: /.*/, answer: 'I parsed this sheet and cross-referenced every detection. Ask me about rooms, doors, windows, quantities or generate a scope of work.' },
  ];
  const hit = canned.find((c) => c.match.test(question)) || canned[canned.length - 1];
  return { answer: hit.answer, citations: ['A-101 Level 12', 'A-001 Cover'], latencyMs: 900 + Math.floor(rand(0, 400)) };
}

