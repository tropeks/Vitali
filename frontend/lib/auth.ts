/**
 * Auth types shared across the frontend.
 * UserDTO mirrors the shape stored in the vitali_user cookie (set by the Django auth endpoint).
 */

export interface UserDTO {
  id: string | number;
  full_name: string;
  email: string;
  role_name?: string | null;
  active_modules: string[];
}
