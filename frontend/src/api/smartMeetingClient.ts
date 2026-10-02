import { isApiErrorBody } from '@/types/api';
import i18n from '@/utils/i18n';

/** JSON body, the raw text otherwise (the Markdown report), undefined when empty */
const parseBody = (text: string, contentType: string): unknown => {
  if (text === '') return undefined;
  if (!contentType.includes('json')) return text;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
};

/** `fetch` to the backend; a network failure becomes a readable error (an abort is rethrown as is) */
const send = async (url: string, options: RequestInit) => {
  try {
    return await fetch(url, options);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new Error(i18n.t('errors.unreachable'));
  }
};

/**
 * Request function of the Orval-generated client (`src/api/generated/`): turns an error response into an `Error`
 * carrying the backend message. The body of a success follows the OpenAPI contract the client is typed from.
 */
const smartMeetingClient = async <T>(url: string, options: RequestInit): Promise<T> => {
  const response = await send(url, options);
  const body = parseBody(await response.text(), response.headers.get('content-type') ?? '');
  if (!response.ok) {
    throw new Error(isApiErrorBody(body) ? body.detail : i18n.t('errors.http', { status: response.status }));
  }

  return body as T;
};

export default smartMeetingClient;
