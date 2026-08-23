const TOKEN_KEY = 'auth_token';
const USER_KEY = 'user';

function purgeLegacyPersistentCredentials() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  } catch {
    // Storage can be disabled by browser policy; session auth still works.
  }
}

// Executes on the first app load after upgrading from a localStorage release.
purgeLegacyPersistentCredentials();

export const getAuthToken = () => sessionStorage.getItem(TOKEN_KEY);
export const getSessionUser = () => sessionStorage.getItem(USER_KEY);

export function storeSession(token, user) {
  sessionStorage.setItem(TOKEN_KEY, token);
  sessionStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
  // Remove credentials written by older releases during the migration.
  purgeLegacyPersistentCredentials();
}
