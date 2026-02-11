/**
 * Authentication Service - Cognito implementation.
 */

import type { User } from '../types/message';
import { CognitoUserPool, CognitoUser, AuthenticationDetails, CognitoUserSession } from 'amazon-cognito-identity-js';

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
  private userPool: CognitoUserPool | null = null;

  constructor() {
    this.loadFromStorage();
    this.initUserPool();
  }

  private initUserPool() {
    const userPoolId = import.meta.env.VITE_USER_POOL_ID;
    const clientId = import.meta.env.VITE_USER_POOL_CLIENT_ID;

    if (userPoolId && clientId) {
      this.userPool = new CognitoUserPool({
        UserPoolId: userPoolId,
        ClientId: clientId
      });
    }
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
   * Login with Cognito username and password.
   */
  async login(username: string, password: string): Promise<User> {
    if (!this.userPool) {
      throw new Error('Cognito not configured');
    }

    return new Promise((resolve, reject) => {
      const authDetails = new AuthenticationDetails({
        Username: username,
        Password: password
      });

      const cognitoUser = new CognitoUser({
        Username: username,
        Pool: this.userPool!
      });

      cognitoUser.authenticateUser(authDetails, {
        onSuccess: (session: CognitoUserSession) => {
          const idToken = session.getIdToken().getJwtToken();
          const payload = session.getIdToken().payload;

          const user: User = {
            id: payload.sub,
            name: payload.name || payload.email || username,
            email: payload.email,
            role: 'analyst',
            permissions: ['cdm_lms', 'cdm_sis', 'cdm_tlm']
          };

          this.state = {
            user,
            isAuthenticated: true,
            token: idToken
          };
          this.saveToStorage();
          resolve(user);
        },
        onFailure: (err) => {
          reject(new Error(err.message || 'Authentication failed'));
        },
        newPasswordRequired: () => {
          reject(new Error('Password change required. Please contact administrator.'));
        }
      });
    });
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
    return this.state.isAuthenticated && !!this.state.token;
  }

  /**
   * Get auth token.
   */
  getToken(): string | null {
    return this.state.token;
  }

  /**
   * Log out current user.
   */
  logout(): void {
    if (this.userPool) {
      const cognitoUser = this.userPool.getCurrentUser();
      if (cognitoUser) {
        cognitoUser.signOut();
      }
    }

    this.state = {
      user: null,
      isAuthenticated: false,
      token: null
    };
    localStorage.removeItem(STORAGE_KEY);
  }
}

// Export singleton instance
export const authService = new AuthService();

// Export class for testing
export { AuthService };
