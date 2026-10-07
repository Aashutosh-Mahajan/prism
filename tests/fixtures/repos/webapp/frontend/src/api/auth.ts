import axios from 'axios';

export interface ApiErrorInfo {
  fields: Record<string, string>;
  message: string;
}

export class EmailNotVerifiedError extends Error {
  info: { email: string; expires_in?: number };

  constructor(info: { email: string; expires_in?: number }) {
    super('Please confirm your email to finish signing in.');
    this.name = 'EmailNotVerifiedError';
    this.info = info;
  }
}

/**
 * Pull readable messages out of an API error. The backend wraps validation
 * errors as {error: {details: [{field, message}]}}; plain DRF errors use
 * {detail} or {field: [messages]}.
 */
export const parseApiError = (err: any): ApiErrorInfo => {
  const data = err?.response?.data;
  const fields: Record<string, string> = {};
  if (data?.error?.details && Array.isArray(data.error.details)) {
    for (const d of data.error.details) {
      const key = d.field || 'non_field_errors';
      if (!fields[key]) fields[key] = String(d.message);
    }
  } else if (data && typeof data === 'object') {
    for (const [key, value] of Object.entries(data)) {
      if (key === 'detail') continue;
      if (Array.isArray(value) && value.length) fields[key] = String(value[0]);
      else if (typeof value === 'string') fields[key] = value;
    }
  }
  const message =
    fields.non_field_errors ||
    data?.detail ||
    (Object.keys(fields).length
      ? ''
      : err?.response
        ? 'Something went wrong. Please try again.'
        : err?.message || 'Network error. Check your connection.');
  return { fields, message };
};

export const login = async (email: string, password: string) => {
  try {
    const res = await axios.post('/api/v1/auth/login/', { email, password });
    return res.data;
  } catch (err: any) {
    if (err?.response?.status === 403) {
      throw new EmailNotVerifiedError({ email, expires_in: err.response.data.expires_in });
    }
    throw err;
  }
};

export const verifyEmail = async (email: string, code: string) => {
  const res = await axios.post('/api/v1/auth/verify-email/', { email, code });
  return res.data;
};
