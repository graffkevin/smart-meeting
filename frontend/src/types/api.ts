import { isRecord, isString } from '@ign-junn/design-system';

/** Error body of the backend (FastAPI `HTTPException`): `{ "detail": "…" }` */
export interface ApiErrorBody {
  detail: string;
}

export const isApiErrorBody = (value: unknown): value is ApiErrorBody => isRecord(value) && isString(value.detail);
