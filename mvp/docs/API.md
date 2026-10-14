# VR-01 Business API — 1.3.0-draft.1

File này được **sinh tự động** từ `backend/openapi.v1.yaml` bằng `tools/gen_api_docs.py`. Không sửa tay; sửa spec rồi chạy lại lệnh sinh.

## Inference plane (cổng 8443)

| Method | Path | operationId | Vai trò | Mô tả | Mã trả về |
|---|---|---|---|---|---|
| GET | `/healthz` | `getLiveness` | anonymous | Liveness - tiến trình còn sống. | 200 |
| GET | `/readyz` | `getReadiness` | anonymous | Readiness - có nhận request kiểm tra mới hay không. | 200, 503 |
| POST | `/v1/inspections` | `submitInspection` | operator | Gửi một ảnh của một sản phẩm để kiểm tra (một ảnh/request, batch 1). | 200, 202, 400, 401, 403, 408, 409, 413, 415, 422, 429, 503 |
| GET | `/v1/inspections` | `listInspections` | viewer, operator, admin | Tra lịch sử kiểm tra, lọc theo product_id và/hoặc state (QC UI, MES simulator). | 200, 400, 401, 403 |
| GET | `/v1/inspections/{request_id}` | `getInspectionStatus` | viewer, operator, admin | Trạng thái xử lý của một request. | 200, 401, 403, 404 |
| GET | `/v1/inspections/{request_id}/result` | `getInspectionResult` | viewer, operator, admin | Kết quả terminal kèm lineage đầy đủ. | 200, 401, 403, 404, 409 |
| POST | `/v1/inspections/{request_id}/cancel` | `cancelInspection` | operator | Hủy một lần kiểm đã nhận nhưng chưa có kết quả. | 200, 400, 401, 403, 404, 409, 415, 503 |
| GET | `/v1/stations/{station_id}/active-recipe` | `getActiveRecipe` | viewer, operator, admin | Recipe đang active của station (để camera/replay gửi đúng recipe_version). | 200, 401, 403, 404, 503 |
| GET | `/v1/me` | `getMe` | viewer, operator, admin | Danh tính và vai trò của token đang dùng, station của edge (để UI chọn màn hình theo quyền). | 200, 401, 403 |
| GET | `/v1/stations/{station_id}/summary` | `getStationSummary` | viewer, operator, admin | Số đếm OK/NG/REVIEW/lỗi kỹ thuật/đã hủy/đang xử lý từ một mốc thời gian (màn Tổng quan). | 200, 400, 401, 403, 404 |
| GET | `/v1/stations/{station_id}/activations` | `listStationActivations` | viewer, operator, admin | Lịch sử chuyển recipe (ai, lúc nào, vì sao, có phải tự rollback) cho mọi vai trò; chỉ đọc, không lộ phần audit khác. | 200, 400, 401, 403, 404 |

## Management plane (cổng 9443)

| Method | Path | operationId | Vai trò | Mô tả | Mã trả về |
|---|---|---|---|---|---|
| GET | `/healthz` | `getLiveness` | anonymous | Liveness - tiến trình còn sống. | 200 |
| GET | `/readyz` | `getReadiness` | anonymous | Readiness - có nhận request kiểm tra mới hay không. | 200, 503 |
| GET | `/v1/admin/packages` | `listPackages` | admin | ModelPackage đã có trong kho đã duyệt. | 200, 401, 403 |
| POST | `/v1/admin/packages/validate` | `validatePackage` | admin | Chạy validator W2-05 (schema, checksum, I/O, golden) cho một package trong kho. | 200, 400, 401, 403, 404, 415, 422 |
| GET | `/v1/admin/recipes` | `listRecipes` | admin | Recipe đã đăng ký và recipe nào đang active. | 200, 401, 403 |
| GET | `/v1/admin/stations/{station_id}` | `getStation` | admin | Recipe active và lịch sử activation của station. | 200, 401, 403, 404, 503 |
| POST | `/v1/admin/stations/{station_id}/activation` | `activateRecipe` | admin | Kích hoạt recipe (và model của nó) cho station sau warm-up + golden check. | 200, 400, 401, 403, 404, 409, 412, 415, 422, 503 |
| POST | `/v1/admin/stations/{station_id}/rollback` | `rollbackRecipe` | admin | Quay về recipe active trước đó (cùng kiểm tra như activation). | 200, 400, 401, 403, 404, 409, 415, 422, 503 |
| GET | `/v1/admin/audit` | `listAudit` | admin | Nhật ký audit (activation, rollback, validate, từ chối xác thực/phân quyền, khởi động). | 200, 400, 401, 403 |

## Giới hạn và timeout (`info.x-limits`, giá trị đề xuất)

| Tên | Giá trị |
|---|---|
| `max_body_bytes` | 6291456 |
| `max_image_bytes` | 4194304 |
| `max_image_width` | 4096 |
| `max_image_height` | 4096 |
| `allowed_image_types` | ['image/png', 'image/jpeg'] |
| `queue_capacity` | 8 |
| `max_inflight` | 1 |
| `queue_timeout_s` | 5 |
| `execution_timeout_s` | 10 |
| `body_read_timeout_s` | 10 |
| `review_band` | 0.05 |
| `list_limit_max` | 100 |

## Trạng thái, kết luận, lý do kỹ thuật

- Trạng thái: `RECEIVED`, `PROCESSING`, `COMPLETED`, `FAILED`, `TIMEOUT`, `INDETERMINATE`, `CANCELLED`
- Kết luận (chỉ khi `COMPLETED`): `OK`, `NG`, `REVIEW`
- Lý do kỹ thuật: `BACKEND_ERROR`, `BACKEND_ID_MISMATCH`, `CANCELLED_BY_CLIENT`, `EXECUTION_TIMEOUT`, `QUEUE_TIMEOUT`, `RESTARTED_DURING_PROCESSING`

## Mã lỗi (`code` trong `application/problem+json`)

`INVALID_REQUEST`, `ALREADY_TERMINAL`, `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `REQUEST_TIMEOUT`, `PAYLOAD_TOO_LARGE`, `UNSUPPORTED_MEDIA_TYPE`, `IMAGE_UNDECODABLE`, `IMAGE_TOO_LARGE_DIMENSIONS`, `RECIPE_NOT_FOUND`, `RECIPE_VERSION_MISMATCH`, `IDEMPOTENCY_CONFLICT`, `RESULT_NOT_READY`, `QUEUE_FULL`, `NOT_READY`, `STORAGE_UNAVAILABLE`, `TRANSITION_BUSY`, `NO_ROLLBACK_TARGET`, `PRECONDITION_FAILED`, `PACKAGE_REJECTED`, `ACTIVATION_GOLDEN_FAILED`, `INTERNAL_ERROR`

## Trường của request gửi ảnh (`InspectionSubmit`)

| Trường | Bắt buộc | Kiểu / ràng buộc |
|---|---|---|
| `request_id` | có | string pattern=^[A-Za-z0-9._:-]{1,128}$ |
| `product_id` | có | string pattern=^[A-Za-z0-9._-]{1,64}$ |
| `product_type` | có | string pattern=^[A-Z0-9_-]{1,32}$ |
| `recipe_version` | có | string pattern=^[a-z][a-z0-9-]{0,63}@[0-9]+\.[0-9]+\.[0-9]+$ |
| `captured_at` | có | string format=date-time |
| `station_id` | có | string pattern=^[a-z][a-z0-9-]{0,63}$ |
| `retry_of` | không | object  |
| `image` | có | object  |
