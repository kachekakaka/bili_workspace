import * as implementation from './library-impl.mjs';

export {
  librarySortValue,
  libraryTagColor,
  splitLibrarySort,
} from './library-impl.mjs';

function takeRequestedGroup() {
  try {
    const value = sessionStorage.getItem('bili-v070-library-group') || '';
    if (value) sessionStorage.removeItem('bili-v070-library-group');
    return value;
  } catch {
    return '';
  }
}

async function waitForAppliedGroup(root, context) {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (!context.isCurrent() || !root.querySelector('#enhLibraryResults .loading-card')) return;
    await new Promise(resolve => setTimeout(resolve, 16));
  }
}

export async function mount(root, context) {
  const requestedGroup = takeRequestedGroup();
  const handle = await implementation.mount(root, context);
  if (requestedGroup && context.isCurrent()) {
    const select = root.querySelector('#enhLibraryGroup');
    const exists = [...(select?.options || [])].some(option => option.value === requestedGroup);
    if (select && exists) {
      select.value = requestedGroup;
      root.querySelector('#enhLibraryApply')?.click();
      await waitForAppliedGroup(root, context);
    }
  }
  return handle || Object.freeze({ dispose() {} });
}
