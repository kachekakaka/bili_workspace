import * as implementation from './tasks-impl.mjs';

export { filterAndSortTasks } from './tasks-impl.mjs';

function takeRequestedOwner() {
  try {
    const value = sessionStorage.getItem('bili-v070-task-owner') || '';
    if (value) sessionStorage.removeItem('bili-v070-task-owner');
    return value;
  } catch {
    return '';
  }
}

export async function mount(root, context) {
  const requestedOwner = takeRequestedOwner();
  const handle = await implementation.mount(root, context);
  if (requestedOwner && context.isCurrent()) {
    const select = root.querySelector('#enhTaskOwner');
    const exists = [...(select?.options || [])].some(option => option.value === requestedOwner);
    if (select && exists) {
      select.value = requestedOwner;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }
  return handle || Object.freeze({ dispose() {} });
}
