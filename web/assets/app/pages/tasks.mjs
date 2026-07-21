import { legacyBridge } from '../legacy/bridge.mjs';

export async function mount(root, context) {
  return legacyBridge.mount('tasks', root, context);
}
