(() => {
  'use strict';
  const E = window.BiliEnhancements;
  if (!E) return;
  const { state, $, $$, esc, api, toast, showModal, scheduleRender, currentPage } = E;
  const UNTAGGED = '__untagged__';
  const OLD_COLORS = {
    '夯': '#dc2626', '顶级': '#7c3aed', '人上人': '#2563eb',
    'NPC': '#64748b', '不要': '#111827',
  };
  const NEW_COLORS = {
    '夯': '#d4a017', '顶级': '#7c3aed', '人上人': '#2563eb',
    'NPC': '#0f766e', '不要': '#dc2626',
  };
  let lastOpenedMediaId = '';

  function tagColor(tag) {
    const name = String(tag?.name || tag || '');
    const configured = String(tag?.color || '').toLowerCase();
    const old = String(OLD_COLORS[name] || '').toLowerCase();
    if (NEW_COLORS[name] && (!configured || configured === old)) return NEW_COLORS[name];
    return E.safeColor(tag?.color || NEW_COLORS[name] || '#64748b');
  }

  function recolorTags(root = document) {
    $$('.enh-tag-chip', root).forEach(chip => {
      const definition = state.tags.find(tag => tag.name === chip.textContent.trim());
      chip.style.setProperty('--tag-color', tagColor(definition || chip.textContent.trim()));
    });
  }

  function groupChips() {
    const current = String(state.library.groupId || '');
    return `<button type="button" class="enh-filter-chip ${current ? '' : 'active'}" data-library-group-chip="">全部分组</button>${state.groups.map(group => `<button type="button" class="enh-filter-chip ${String(group.id) === current ? 'active' : ''}" data-library-group-chip="${esc(group.id)}">${esc(group.display_name)}</button>`).join('')}`;
  }

  function tagChips() {
    const current = String(state.library.tag || '');
    const all = `<button type="button" class="enh-filter-chip ${current ? '' : 'active'}" data-library-tag-chip="">全部标签</button>`;
    const untagged = `<button type="button" class="enh-filter-chip enh-untagged-chip ${current === UNTAGGED ? 'active' : ''}" data-library-tag-chip="${UNTAGGED}">无标签</button>`;
    const tags = state.tags.map(tag => `<button type="button" class="enh-filter-chip enh-colored-filter-chip ${tag.name === current ? 'active' : ''}" style="--tag-color:${tagColor(tag)}" data-library-tag-chip="${esc(tag.name)}">${esc(tag.name)}</button>`).join('');
    return all + untagged + tags;
  }

  function applyLibraryFilters() {
    const button = $('#enhLibraryApply');
    if (button) button.click(); else scheduleRender(10);
  }

  function ensureFilterChips(view) {
    const filterCard = $('.enh-library-filter-card', view) || $('.card', view);
    const grid = $('.enh-filter-grid', filterCard) || $('.form-grid', filterCard);
    const groupSelect = $('#enhLibraryGroup', view);
    const tagSelect = $('#enhLibraryTag', view);
    if (!filterCard || !grid || !groupSelect || !tagSelect) return;
    groupSelect.closest('.field')?.classList.add('enh-native-chip-filter');
    tagSelect.closest('.field')?.classList.add('enh-native-chip-filter');
    if (![...tagSelect.options].some(option => option.value === UNTAGGED)) {
      const option = document.createElement('option');
      option.value = UNTAGGED;
      option.textContent = '无标签';
      tagSelect.insertBefore(option, tagSelect.options[1] || null);
    }
    tagSelect.value = state.library.tag || '';
    groupSelect.value = state.library.groupId || '';
    let chips = $('#enhLibraryChipFilters', view);
    if (!chips) {
      chips = document.createElement('div');
      chips.id = 'enhLibraryChipFilters';
      chips.className = 'enh-library-chip-filters';
      filterCard.insertBefore(chips, grid);
    }
    const signature = JSON.stringify({
      group: state.library.groupId || '',
      tag: state.library.tag || '',
      groups: state.groups.map(group => [group.id, group.display_name]),
      tags: state.tags.map(tag => [tag.name, tag.color]),
    });
    if (chips.dataset.signature !== signature) {
      chips.dataset.signature = signature;
      chips.innerHTML = `<div class="enh-chip-filter-row"><span class="enh-chip-filter-label">▦ 分组</span><div class="enh-chip-strip">${groupChips()}</div></div><div class="enh-chip-filter-row"><span class="enh-chip-filter-label">⌁ 标签</span><div class="enh-chip-strip">${tagChips()}</div></div>`;
    }
  }

  function ensureMoveButtons(view) {
    $$('[data-library-id]', view).forEach(card => {
      const mediaId = card.dataset.libraryId;
      const actions = $('.media-actions', card);
      if (!mediaId || !actions || $('[data-catalog-move]', actions)) return;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn small';
      button.dataset.catalogMove = mediaId;
      button.textContent = '▦ 改分组';
      actions.appendChild(button);
    });
  }

  async function moveMedia(mediaId) {
    const item = (state.library.data?.items || []).find(value => value.id === mediaId);
    const currentGroupId = item?.group_id || '';
    const modal = showModal('修改作品分组', `<form id="enhMoveMediaForm" class="form-grid"><div class="field full"><label>目标分组</label><select id="enhMoveMediaGroup" class="select">${E.groupOptions(currentGroupId)}</select><small>修改的是作品库逻辑分组，不会重复下载媒体文件。</small></div><div class="field full"><button type="submit" class="btn primary">保存分组</button></div></form>`, { narrow: true });
    $('#enhMoveMediaForm', modal.root).onsubmit = async event => {
      event.preventDefault();
      const button = $('button[type="submit"]', event.currentTarget);
      button.disabled = true;
      try {
        const response = await api(`/api/library/${encodeURIComponent(mediaId)}/move`, {
          method: 'POST', body: { group_id: $('#enhMoveMediaGroup', modal.root).value },
        });
        if (item) {
          item.group_id = response.data?.group_id || $('#enhMoveMediaGroup', modal.root).value;
          item.group_name = response.data?.group_name || response.data?.group || item.group_name;
        }
        modal.close();
        toast('作品分组已修改', 'good');
        scheduleRender(10);
      } catch (error) {
        toast(error.message, 'bad');
      } finally {
        button.disabled = false;
      }
    };
  }

  function enhanceLibraryView() {
    if (currentPage() !== 'library') return;
    const view = $('[data-enhanced-view="library"]');
    if (!view) return;
    ensureFilterChips(view);
    ensureMoveButtons(view);
    recolorTags(view);
  }

  function enhanceModal() {
    const modal = $('#modalRoot:not(.hidden)');
    if (!modal || !lastOpenedMediaId || !$('#enhMediaPlayer', modal)) return;
    const toolbar = $('.modal-body .toolbar', modal);
    if (!toolbar || $('#enhMoveCurrentMediaGroup', toolbar)) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'enhMoveCurrentMediaGroup';
    button.className = 'btn';
    button.textContent = '▦ 修改分组';
    button.onclick = () => moveMedia(lastOpenedMediaId);
    toolbar.appendChild(button);
  }

  document.addEventListener('click', event => {
    const element = event.target instanceof Element ? event.target : null;
    if (!element) return;
    const open = element.closest('[data-library-open]');
    if (open) lastOpenedMediaId = open.dataset.libraryOpen || '';
    const move = element.closest('[data-catalog-move]');
    if (move) {
      event.preventDefault();
      event.stopImmediatePropagation();
      void moveMedia(move.dataset.catalogMove);
      return;
    }
    const groupChip = element.closest('[data-library-group-chip]');
    if (groupChip) {
      event.preventDefault();
      state.library.groupId = groupChip.dataset.libraryGroupChip || '';
      const select = $('#enhLibraryGroup');
      if (select) select.value = state.library.groupId;
      state.library.page = 1;
      applyLibraryFilters();
      return;
    }
    const tagChip = element.closest('[data-library-tag-chip]');
    if (tagChip) {
      event.preventDefault();
      state.library.tag = tagChip.dataset.libraryTagChip || '';
      const select = $('#enhLibraryTag');
      if (select) select.value = state.library.tag;
      state.library.page = 1;
      applyLibraryFilters();
    }
  }, true);

  const root = $('#pageRoot');
  if (root) new MutationObserver(() => requestAnimationFrame(enhanceLibraryView)).observe(root, { childList: true, subtree: true });
  const modalRoot = $('#modalRoot');
  if (modalRoot) new MutationObserver(() => requestAnimationFrame(enhanceModal)).observe(modalRoot, { childList: true, subtree: true, attributes: true });
  window.addEventListener('hashchange', () => requestAnimationFrame(enhanceLibraryView));
  requestAnimationFrame(() => { enhanceLibraryView(); recolorTags(document); });
})();
