import { legacyBridge } from '../legacy/bridge.mjs';

export async function mount(root, context) {
  return legacyBridge.mount('library', root, context);
}
