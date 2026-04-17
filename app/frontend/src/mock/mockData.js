// Mock data for TakeOff.ai SaaS clone

export const NAV_LINKS = [
  { label: 'Product', href: '/features', hasDropdown: true },
  { label: 'Trades', href: '/trades', hasDropdown: true },
  { label: 'Compare', href: '/compare/bluebeam', hasDropdown: true },
  { label: 'Pricing', href: '/pricing' },
  { label: 'Company', href: '/about' },
];

export const PARTNER_LOGOS = [
  'Northridge Build', 'Cascade Group', 'Bluestone Co', 'Ironbridge', 'Meridian Construction',
  'Hallmark GC', 'Kingsford & Co', 'Pinnacle Precast', 'Summit Trades', 'Archer Builders',
  'Vantage Works', 'Fieldstone', 'Harbourline', 'Cornerstone Ltd', 'Ridgeview',
  'Oakspire', 'Thornhill', 'Westbrook'
];

export const HERO_STATS = [
  { value: '5×', label: 'Faster takeoffs' },
  { value: '98%', label: 'Detection accuracy' },
  { value: '$1M', label: 'Avg. yearly savings' },
  { value: '12K+', label: 'Estimators onboard' },
];

export const FEATURES = [
  {
    id: 'ai-detection',
    title: 'AI Room & Area Detection',
    kicker: 'Computer vision',
    desc: 'Upload any blueprint and our model identifies rooms, walls, doors and windows in seconds, not hours.',
    accent: 'indigo',
  },
  {
    id: 'realtime',
    title: 'Real-time Collaboration',
    kicker: 'Cloud-native',
    desc: 'Multiple estimators work on the same project simultaneously with live cursors, comments and revisions.',
    accent: 'violet',
  },
  {
    id: 'compare',
    title: 'Revision Compare',
    kicker: 'Overlay & diff',
    desc: 'Quantify drawing changes with one click. Toggle between sets and see adds, deletes and edits highlighted.',
    accent: 'cyan',
  },
  {
    id: 'chat',
    title: 'TakeOff Chat',
    kicker: 'LLM assistant',
    desc: 'Ask natural language questions about any plan. Scope, RFPs and counts generated instantly from drawings.',
    accent: 'emerald',
  },
  {
    id: 'export',
    title: 'Smart Exports',
    kicker: 'Excel, CSV, JSON',
    desc: 'Export filtered quantities by trade, floor or area. Connect to your estimating workflow with one click.',
    accent: 'amber',
  },
  {
    id: 'any-file',
    title: 'Every File Type',
    kicker: 'PDF, TIFF, PNG',
    desc: 'Even hand-drawn plans. Auto-scale detection works across every file type your architect sends over.',
    accent: 'rose',
  },
];

export const TRADES = [
  { slug: 'drywall', name: 'Drywall', icon: 'LayoutPanelLeft', desc: 'Linear walls, partitions and ceiling grid counts with surface area breakdowns.' },
  { slug: 'electrical', name: 'Electrical', icon: 'Zap', desc: 'Outlets, fixtures, panels and conduit runs auto-counted per floor.' },
  { slug: 'ffe', name: 'Furniture, Fixtures & Equipment', icon: 'Armchair', desc: 'FF&E schedules generated from symbols and legends.' },
  { slug: 'gc', name: 'General Contracting', icon: 'HardHat', desc: 'Cross-trade rollups, bid coverage and exports.' },
  { slug: 'glazing', name: 'Glazing, Windows & Doors', icon: 'Square', desc: 'Window/door counts with dimensions and schedule matching.' },
  { slug: 'landscaping', name: 'Landscaping', icon: 'Trees', desc: 'Site area, planters, paving and irrigation measurements.' },
  { slug: 'mechanical', name: 'Mechanical / HVAC', icon: 'Wind', desc: 'Ductwork linears, diffuser counts and equipment schedules.' },
  { slug: 'painting', name: 'Painting & Wallpaper', icon: 'Paintbrush', desc: 'Paintable surface areas per room with finish legend.' },
  { slug: 'plumbing', name: 'Plumbing', icon: 'Droplet', desc: 'Fixture counts, pipe runs and riser diagrams parsed from plans.' },
  { slug: 'other', name: 'Other Trades', icon: 'Hammer', desc: 'Concrete, steel, roofing and specialty work with custom libraries.' },
];

export const TESTIMONIALS = [
  {
    quote: 'TakeOff paid for itself in a week. Our 30-story high-rise takeoff went from two weeks to under 48 hours. We keep our pipeline full now.',
    name: 'Brad Preston', role: 'President', company: 'Total Flooring Contractors', accent: 'indigo',
  },
  {
    quote: 'It is like adding three estimators to a two-person team without the headcount. The AI catches patterns we used to miss by hand.',
    name: 'Joanne Howell', role: 'Director of Preconstruction', company: 'MPC General', accent: 'violet',
  },
  {
    quote: 'Cloud collaboration changed our subcontractor workflow entirely. Everyone sees the same numbers in real time. No more emailed PDFs.',
    name: 'Foster Gallen', role: 'Estimator', company: 'Innovative Construction Management', accent: 'cyan',
  },
  {
    quote: 'Customer support responds within minutes, training is built in and the tool just works. Indispensable from day one.',
    name: 'Derek Hickman', role: 'Head of Estimating', company: 'SR Construction Services', accent: 'emerald',
  },
  {
    quote: 'We used legacy software for 13 years. TakeOff gave back 20% of every workday. Bids move faster, wins go up.',
    name: 'Marcus Nightingale', role: 'Senior Estimator', company: 'L&L Painting Co.', accent: 'amber',
  },
  {
    quote: 'Being able to ask the plan a question and get an answer back in seconds is wild. Scope gaps surface before they cost us money.',
    name: 'Sam Morrow', role: 'Estimator', company: 'Leathertown Lumber', accent: 'rose',
  },
];

export const AWARDS = [
  { name: 'ACG Innovation Award', year: '2024' },
  { name: 'StartupCity Top 10', year: '2024' },
  { name: 'Emerge Award', year: '2023' },
  { name: 'Preconstruction Badge', year: '2024' },
  { name: 'BuiltWorlds Top 50', year: '2023' },
  { name: 'Venture Pitch Winner', year: '2024' },
];

export const PRICING_PLANS = [
  {
    name: 'Starter',
    tagline: 'For solo estimators getting started with AI.',
    price: '$199',
    period: '/mo',
    billing: 'billed yearly, per user',
    features: [
      'Up to 10 projects / month',
      'AI area & linear takeoffs',
      'PDF, PNG, TIFF support',
      'Personal library',
      'Email support',
    ],
    cta: 'Start free trial',
    highlight: false,
  },
  {
    name: 'Growth',
    tagline: 'Built for small estimating teams winning more bids.',
    price: '$299',
    period: '/mo',
    billing: 'billed yearly, per user',
    features: [
      'Unlimited automated takeoffs',
      'Unlimited TakeOff Chat prompts',
      'Image & symbol search',
      'Internal + external collaboration',
      'Revision compare',
      'Priority support (20 min SLA)',
    ],
    cta: 'Start free trial',
    highlight: true,
  },
  {
    name: 'Business',
    tagline: 'For estimating departments with 4+ users.',
    price: 'Custom',
    period: '',
    billing: 'contact sales for pricing',
    features: [
      'Everything in Growth',
      'Dedicated onboarding & training',
      'SSO / SAML',
      'Classification library template',
      'Security & compliance review',
      'Named support representative',
    ],
    cta: 'Book a demo',
    highlight: false,
  },
];

export const PRICING_FAQ = [
  { q: 'How does the free trial work?', a: '14 days of full access to the Growth plan — no credit card needed. Keep your work when you upgrade.' },
  { q: 'Which payment methods do you accept?', a: 'All major credit cards, ACH for annual plans, and invoicing for Business tier.' },
  { q: 'Can I invite collaborators outside my organization?', a: 'Yes. External collaborators can view or edit takeoffs with granular permissions — no TakeOff account required to view.' },
  { q: 'Do you offer discounts for multiple licenses?', a: 'Yes. Volume discounts apply automatically at 4+ seats. Reach out to sales for 25+ seat pricing.' },
  { q: 'What if I need enterprise compliance?', a: 'Business plan includes SOC 2, SSO, audit logs and a named CSM. Request a security packet from our team.' },
  { q: 'What happens when I cancel?', a: 'You keep access through the end of your billing period. Export all projects any time as Excel, CSV or JSON.' },
];

export const COMPARISON_FEATURES = [
  { group: 'AI & Search', items: [
    { name: 'AI Image Search', us: true, blueBeam: false, ost: false, planSwift: false },
    { name: 'Text Search across drawings', us: true, blueBeam: true, ost: false, planSwift: false },
    { name: 'TakeOff GPT chat', us: true, blueBeam: false, ost: false, planSwift: false },
    { name: 'Symbol classification', us: true, blueBeam: false, ost: false, planSwift: false },
  ]},
  { group: 'Functionality', items: [
    { name: 'Cloud-based', us: true, blueBeam: false, ost: false, planSwift: false },
    { name: 'Curved linear takeoffs', us: true, blueBeam: true, ost: true, planSwift: true },
    { name: 'Real-time internal collaboration', us: true, blueBeam: false, ost: false, planSwift: false },
    { name: 'Real-time external collaboration', us: true, blueBeam: false, ost: false, planSwift: false },
    { name: 'Auto scale detection', us: true, blueBeam: false, ost: false, planSwift: false },
    { name: 'Drawing revision management', us: true, blueBeam: true, ost: false, planSwift: false },
    { name: 'Smart copy & paste', us: true, blueBeam: false, ost: false, planSwift: false },
    { name: 'Metric + Imperial in same project', us: true, blueBeam: false, ost: false, planSwift: false },
  ]},
  { group: 'Support & UX', items: [
    { name: 'In-app training videos', us: true, blueBeam: true, ost: true, planSwift: true },
    { name: 'Dedicated CSM', us: true, blueBeam: false, ost: false, planSwift: false },
    { name: '20-min response SLA', us: true, blueBeam: false, ost: false, planSwift: false },
    { name: 'Web-based', us: true, blueBeam: false, ost: false, planSwift: false },
  ]},
];

export const COMPETITORS = {
  bluebeam: {
    name: 'Bluebeam',
    tagline: 'PDF markup, not a full takeoff tool',
    pros: ['Large suite of PDF markup tools', 'Document management + bookmarks', 'Familiar to longtime estimators'],
    cons: ['Not a full takeoff tool — markup only', 'Slow lag when quantifying large plans', 'Frequent crashes reported', 'No AI, no cloud collaboration'],
  },
  ost: {
    name: 'Onscreen Takeoff (OST)',
    tagline: 'Legacy desktop software from another era',
    pros: ['Legacy brand recognition', '“Double-side” wall measurement', 'Free training videos'],
    cons: ['Desktop only, no cloud', 'Frequent crashes & lost work', 'TIFF files only', 'Users describe it as “cumbersome & slow”'],
  },
  planswift: {
    name: 'PlanSwift',
    tagline: 'Outdated interface with steep learning curve',
    pros: ['Flexible assemblies', 'Integrates with older spreadsheets', 'Broad file support'],
    cons: ['Complex UI, long onboarding', 'No AI or semantic search', 'Limited collaboration', 'Quantity errors on complex plans'],
  },
};

export const SAMPLE_PROJECTS = [
  { id: 'p_001', name: 'Waterford Tower — Level 12', status: 'Active', type: 'High-rise residential', updated: '2 hours ago', sheets: 42, progress: 78, owner: 'You' },
  { id: 'p_002', name: 'Meridian Medical Campus', status: 'Active', type: 'Healthcare', updated: '5 hours ago', sheets: 128, progress: 45, owner: 'Alex Rivera' },
  { id: 'p_003', name: 'Oak Grove Elementary Renovation', status: 'Review', type: 'Education', updated: 'Yesterday', sheets: 64, progress: 92, owner: 'You' },
  { id: 'p_004', name: 'Harborline Distribution Center', status: 'Active', type: 'Industrial', updated: '2 days ago', sheets: 87, progress: 31, owner: 'Priya Patel' },
  { id: 'p_005', name: 'Westbrook Mixed-Use Plaza', status: 'Draft', type: 'Mixed-use', updated: '3 days ago', sheets: 19, progress: 12, owner: 'You' },
  { id: 'p_006', name: 'Ironbridge Retail Pad B', status: 'Archived', type: 'Retail', updated: 'Mar 14', sheets: 22, progress: 100, owner: 'Jordan Kim' },
];

export const DASHBOARD_ACTIVITY = [
  { icon: 'Sparkles', text: 'AI detected 142 objects on Level 12 — Waterford Tower', time: '12m ago', color: 'indigo' },
  { icon: 'MessageSquare', text: 'Alex commented on Meridian Medical Campus', time: '1h ago', color: 'violet' },
  { icon: 'GitCompare', text: 'Revision B vs C compared on Oak Grove', time: '3h ago', color: 'cyan' },
  { icon: 'Download', text: 'Exported quantities for Harborline DC to Excel', time: 'Yesterday', color: 'emerald' },
  { icon: 'Users', text: 'Priya joined as a collaborator on Westbrook Plaza', time: '2d ago', color: 'amber' },
];

export const DEMO_STEPS = [
  { step: 1, title: 'Upload your plans', desc: 'Drag any PDF, TIFF or image. Even hand-drawn. Auto-scale detects dimensions within seconds.' },
  { step: 2, title: 'AI analyzes everything', desc: 'Rooms, walls, doors, windows and fixtures are detected with >98% accuracy per sheet.' },
  { step: 3, title: 'Review on the canvas', desc: 'Zoom, pan and toggle layers. Hover detections to see dimensions and confidence scores.' },
  { step: 4, title: 'Export quantities', desc: 'Filter by trade, floor or area. Push to Excel, CSV or JSON for your estimating workflow.' },
];

