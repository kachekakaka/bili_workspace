import { once } from '../core/lifecycle.mjs';

function optionLabel(option) {
  return option?.textContent?.trim() || '请选择';
}

export function mountSearchableSelect(select, {
  modal,
  threshold = 8,
  force = false,
  documentRef = globalThis.document,
} = {}) {
  if (!(select instanceof documentRef.defaultView.HTMLSelectElement)) {
    throw new TypeError('select must be an HTMLSelectElement');
  }
  if (!modal?.open || (!force && select.options.length <= threshold)) {
    return Object.freeze({ dispose: () => false, enhanced: false });
  }
  if (select.dataset.v070Searchable === '1') {
    return Object.freeze({ dispose: () => false, enhanced: true });
  }

  const originalParent = select.parentNode;
  const originalNext = select.nextSibling;
  const wrapper = documentRef.createElement('div');
  wrapper.className = 'v062-search-select';
  originalParent.insertBefore(wrapper, select);
  wrapper.appendChild(select);
  select.classList.add('v062-native-select');
  select.dataset.v070Searchable = '1';
  const trigger = documentRef.createElement('button');
  trigger.type = 'button';
  trigger.className = 'v062-select-trigger';
  trigger.setAttribute('aria-haspopup', 'dialog');
  trigger.innerHTML = '<span class="v062-select-trigger-label"></span><span aria-hidden="true">⌄</span>';
  wrapper.appendChild(trigger);
  const label = trigger.querySelector('.v062-select-trigger-label');
  const sync = () => { label.textContent = optionLabel(select.selectedOptions[0]); };
  const controller = new AbortController();

  const open = () => {
    const options = [...select.options].filter(option => !option.disabled);
    const instance = modal.open({
      title: select.closest('.field')?.querySelector('label')?.textContent?.trim() || '选择项目',
      narrow: true,
      body: '<div class="field"><label for="v062SelectSearch">搜索</label><input id="v062SelectSearch" class="input" type="search" placeholder="输入关键词筛选"></div><div id="v062SelectOptions" class="v062-select-option-grid" role="listbox"></div>',
    });
    const search = instance.body.querySelector('#v062SelectSearch');
    const list = instance.body.querySelector('#v062SelectOptions');
    const render = query => {
      const keyword = String(query || '').trim().toLocaleLowerCase();
      const filtered = options.filter(option => !keyword || optionLabel(option).toLocaleLowerCase().includes(keyword));
      list.replaceChildren();
      if (!filtered.length) {
        const empty = documentRef.createElement('div');
        empty.className = 'empty';
        empty.textContent = '没有匹配的选项';
        list.appendChild(empty);
        return;
      }
      for (const option of filtered) {
        const button = documentRef.createElement('button');
        button.type = 'button';
        button.className = `v062-select-option ${option.selected ? 'active' : ''}`.trim();
        button.dataset.v062Option = option.value;
        button.setAttribute('role', 'option');
        button.setAttribute('aria-selected', option.selected ? 'true' : 'false');
        button.textContent = optionLabel(option);
        button.onclick = () => {
          select.value = option.value;
          select.dispatchEvent(new Event('input', { bubbles: true }));
          select.dispatchEvent(new Event('change', { bubbles: true }));
          sync();
          instance.close('select');
        };
        list.appendChild(button);
      }
    };
    search.addEventListener('input', () => render(search.value));
    render('');
    requestAnimationFrame(() => search.focus());
  };

  trigger.addEventListener('click', open, { signal: controller.signal });
  select.addEventListener('change', sync, { signal: controller.signal });
  sync();

  return Object.freeze({
    enhanced: true,
    dispose: once(() => {
      controller.abort();
      select.classList.remove('v062-native-select');
      delete select.dataset.v070Searchable;
      if (originalNext && originalNext.parentNode === originalParent) originalParent.insertBefore(select, originalNext);
      else originalParent.appendChild(select);
      wrapper.remove();
    }),
  });
}
