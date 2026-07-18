(() => {
  'use strict';
  const E = window.BiliEnhancements;
  if (!E) return;
  const oldColors = {
    '夯': '#dc2626', '顶级': '#7c3aed', '人上人': '#2563eb',
    'NPC': '#64748b', '不要': '#111827',
  };
  const newColors = {
    '夯': '#d4a017', '顶级': '#7c3aed', '人上人': '#2563eb',
    'NPC': '#0f766e', '不要': '#dc2626',
  };
  E.catalogTagColor = tag => {
    const name = String(tag?.name || tag || '');
    const configured = String(tag?.color || '').toLowerCase();
    const old = String(oldColors[name] || '').toLowerCase();
    if (newColors[name] && (!configured || configured === old)) return newColors[name];
    return E.safeColor(tag?.color || newColors[name] || '#64748b');
  };
})();
