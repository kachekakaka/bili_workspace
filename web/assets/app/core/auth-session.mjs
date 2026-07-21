function freezeSnapshot(value) {
  const user = value?.user && typeof value.user === 'object' ? Object.freeze({ ...value.user }) : null;
  return Object.freeze({
    authenticated: Boolean(value?.authenticated),
    required: Boolean(value?.required),
    setupRequired: Boolean(value?.setup_required ?? value?.setupRequired),
    mustChangePassword: Boolean(value?.must_change_password ?? value?.mustChangePassword),
    csrfToken: String(value?.csrf_token ?? value?.csrfToken ?? ''),
    username: String(value?.username ?? user?.username ?? ''),
    displayName: String(value?.display_name ?? value?.displayName ?? user?.display_name ?? ''),
    role: String(value?.role ?? user?.role ?? 'user'),
    permissions: Object.freeze([...(value?.permissions || [])].map(String)),
    user,
  });
}

export function createSessionStore(initial = {}) {
  let snapshot = freezeSnapshot(initial);
  const listeners = new Set();

  const emit = previous => {
    for (const listener of [...listeners]) listener(snapshot, previous);
  };

  return Object.freeze({
    get() {
      return snapshot;
    },
    set(value) {
      const previous = snapshot;
      snapshot = freezeSnapshot(value || {});
      emit(previous);
      return snapshot;
    },
    patch(value) {
      const current = snapshot;
      return this.set({
        ...current,
        ...value,
        setup_required: value?.setup_required ?? value?.setupRequired ?? current.setupRequired,
        must_change_password: value?.must_change_password ?? value?.mustChangePassword ?? current.mustChangePassword,
        csrf_token: value?.csrf_token ?? value?.csrfToken ?? current.csrfToken,
        display_name: value?.display_name ?? value?.displayName ?? current.displayName,
      });
    },
    clear() {
      return this.set({});
    },
    subscribe(listener, { immediate = false } = {}) {
      if (typeof listener !== 'function') throw new TypeError('listener must be a function');
      listeners.add(listener);
      if (immediate) listener(snapshot, snapshot);
      let active = true;
      return () => {
        if (!active) return false;
        active = false;
        listeners.delete(listener);
        return true;
      };
    },
    isAdmin() {
      return snapshot.role === 'admin';
    },
    can(permission) {
      const name = String(permission || '');
      return snapshot.permissions.includes('admin:*') || snapshot.permissions.includes(name);
    },
  });
}
