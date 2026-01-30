/**
 * Authentication Service - Stub implementation.
 *
 * For initial development, uses API key authentication.
 * SSO integration hooks prepared for Phase 4.
 */

import type { User } from '../types/message';

export type SSOProvider = 'okta' | 'azure-ad' | 'adfs' | 'shibboleth';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  token: string | null;
}

const STORAGE_KEY = 'illuminate_auth';

class AuthService {
  private state: AuthState = {
    user: null,
    isAuthenticated: false,
    token: null
  };

  constructor() {
    this.loadFromStorage();
  }

  private loadFromStorage(): void {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        this.state = JSON.parse(stored);
      }
    } catch {
      // Ignore storage errors
    }
  }

  private saveToStorage(): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.state));
    } catch {
      // Ignore storage errors
    }
  }

  /**
   * Validate API key and create session.
   * Stub implementation for development.
   */
  async validateApiKey(apiKey: string): Promise<User | null> {
    // In development, accept any non-empty key
    if (import.meta.env.DEV || import.meta.env.VITE_MOCK_MODE === 'true') {
      if (apiKey && apiKey.length > 0) {
        const user: User = {
          id: 'dev-user',
          name: 'Development User',
          role: 'analyst',
          permissions: ['cdm_lms', 'cdm_sis', 'cdm_tlm', 'cdm_clb', 'cdm_media']
        };

        this.state = {
          user,
          isAuthenticated: true,
          token: apiKey
        };
        this.saveToStorage();

        return user;
      }
      return null;
    }

    // Production: validate against backend
    try {
      const response = await fetch(`${import.meta.env.VITE_API_URL}/api/auth/validate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`
        }
      });

      if (!response.ok) {
        return null;
      }

      const user = await response.json();

      this.state = {
        user,
        isAuthenticated: true,
        token: apiKey
      };
      this.saveToStorage();

      return user;
    } catch {
      return null;
    }
  }

  /**
   * Initiate SSO login flow.
   * Hook for Phase 4 integration.
   */
  async initiateSSOLogin(provider: SSOProvider): Promise<void> {
    // SSO not yet configured
    throw new Error(`SSO provider '${provider}' not yet configured. Use API key authentication.`);
  }

  /**
   * Handle SSO callback.
   * Hook for Phase 4 integration.
   */
  async handleSSOCallback(code: string, state: string): Promise<User | null> {
    // SSO not yet configured
    console.log('SSO callback received:', { code, state });
    throw new Error('SSO not yet configured. Use API key authentication.');
  }

  /**
   * Get current user.
   */
  getUser(): User | null {
    return this.state.user;
  }

  /**
   * Check if user is authenticated.
   */
  isAuthenticated(): boolean {
    return this.state.isAuthenticated;
  }

  /**
   * Get auth token.
   */
  getToken(): string | null {
    return this.state.token;
  }

  /**
   * Check if user has permission.
   */
  hasPermission(permission: string): boolean {
    return this.state.user?.permissions.includes(permission) || false;
  }

  /**
   * Log out current user.
   */
  logout(): void {
    this.state = {
      user: null,
      isAuthenticated: false,
      token: null
    };
    localStorage.removeItem(STORAGE_KEY);
  }

  /**
   * Auto-login for development mode.
   */
  devLogin(): User {
    const user: User = {
      id: 'dev-user',
      name: 'Development User',
      role: 'analyst',
      permissions: ['cdm_lms', 'cdm_sis', 'cdm_tlm', 'cdm_clb', 'cdm_media']
    };

    this.state = {
      user,
      isAuthenticated: true,
      token: 'dev-token'
    };
    this.saveToStorage();

    return user;
  }
}

// Export singleton instance
export const authService = new AuthService();

// Export class for testing
export { AuthService };
