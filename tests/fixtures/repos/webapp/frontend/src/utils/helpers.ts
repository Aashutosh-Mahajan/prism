export const getDashboardRouteForRole = (role?: string | null): string | null => {
  if (role === 'restaurant_owner') return '/dashboard/restaurant-owner';
  if (role === 'admin') return '/dashboard/admin';
  return null;
};

export const getPostAuthRedirectPath = (role?: string | null): string => {
  return getDashboardRouteForRole(role) || '/dashboard';
};

export const formatMoney = (value: number): string => `₹${value.toFixed(2)}`;
