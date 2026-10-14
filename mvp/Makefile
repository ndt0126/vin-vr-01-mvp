# VR-01 MVP - mot lenh cho moi viec. Chay trong thu muc mvp/.
# GPU=1: them cau hinh GPU cho Triton. Dat VR01_GPU=1 trong deploy/.env de moi lenh make deu dung GPU (khuyen dung tren may GPU).
GPU ?= $(shell grep -qs '^VR01_GPU=1' deploy/.env && echo 1)
# SLOW=1: them fixture model-slow (chi de test timeout/cancel/drain).  VR01_SLOW_ROUNDS=N: chinh do cham.
# HEAVY=tiny|cpu|gpu|gpu-xl: them model-heavy (mang tich chap that, backend triton-onnx-v1) cho bai hieu nang.
INIT_EXTRA = $(if $(SLOW),--with-slow-fixture,) $(if $(HEAVY),--with-heavy-fixture $(HEAVY),)
COMPOSE = HOST_UID=$$(id -u) HOST_GID=$$(id -g) INIT_EXTRA="$(INIT_EXTRA)" docker compose --env-file deploy/.env -f deploy/docker-compose.yml $(if $(GPU),-f deploy/docker-compose.gpu.yml,)
PY ?= python3

.PHONY: env build init start stop down logs smoke load docs report backup restore obs-start obs-stop alerts-test trace diag status test test-local e2e e2e-setup digests clean

env:
	@test -f deploy/.env || cp deploy/.env.sample deploy/.env

build: env          ## build image api
	$(COMPOSE) build init

init: build         ## tao token lab, chung chi TLS lab, Triton model repository trong run/
	@mkdir -p run
	$(COMPOSE) run --rm init

start: init         ## bat Triton + API, cho toi khi healthy
	$(COMPOSE) up -d --wait triton api
	@if [ -f run/examples.changed ] && [ -n "$$(docker ps -q -f name=vr01-mvp-api-1)" ]; then echo 'kho package da doi: khoi dong lai API'; $(COMPOSE) restart api >/dev/null && $(COMPOSE) up -d --wait api; fi; rm -f run/examples.changed

stop:               ## dung, giu du lieu trong run/
	$(COMPOSE) stop

down:               ## go container va mang (ca Prometheus/Grafana neu da bat), giu du lieu trong run/
	$(COMPOSE) --profile obs --profile tools down --remove-orphans

logs:
	$(COMPOSE) logs --tail=100

smoke:              ## smoke flow tren stack dang chay (can python3 tren host, chi dung thu vien chuan)
	$(PY) tests/smoke.py --run-dir run

load:               ## chuyen recipe duoi tai lien tuc tren stack dang chay (W3-04)
	$(PY) tests/load_cutover.py --run-dir run --rate 10 --duration 120 --cutover-every 10

docs:               ## sinh lai docs/API.md, docs/OBSERVABILITY.md va dashboard Grafana
	$(PY) tools/gen_api_docs.py
	$(PY) tools/gen_observability_docs.py
	$(PY) tools/gen_dashboard.py

report:             ## sinh TEST-REPORT.md tu cac file JSON/log trong evidence/
	$(PY) tools/make_test_report.py

backup:             ## sao luu ledger + trace + anh vao run/backup/ (chay duoc khi stack dang bat)
	$(PY) tools/backup.py backup --run-dir run

restore:            ## make restore BACKUP=run/backup/backup-...  (dung stack, khoi phuc, bat lai; du lieu cu duoc doi ten)
	@test -n "$(BACKUP)" || (echo "usage: make restore BACKUP=run/backup/<ten>"; exit 2)
	$(COMPOSE) stop
	$(PY) tools/backup.py restore --run-dir run --from $(BACKUP)
	$(COMPOSE) up -d --wait triton api

obs-start: start    ## bat them Prometheus (:9091) va Grafana (:3000) - chi loopback
	$(COMPOSE) --profile obs up -d prometheus grafana

obs-stop:
	$(COMPOSE) --profile obs stop prometheus grafana

alerts-test: env    ## kiem luat canh bao bang promtool (offline, khong can stack)
	$(COMPOSE) --profile obs run --rm --no-deps -v "$(CURDIR)/deploy/observability:/w" -w /w --entrypoint promtool prometheus test rules alerts.test.yml

trace:              ## make trace ID=<request_id>: toan bo duong di cua mot request (ledger + log + audit)
	@$(PY) tools/trace_request.py --run-dir run $(ID)

e2e-setup:          ## mot lan: cai Playwright (can node >= 20 va Internet) cho test UI
	cd tests/e2e && npm ci --no-audit --no-fund && npx playwright-core install chromium

e2e:                ## test E2E giao dien /ui/ tren stack dang chay (W5-02); ket qua + anh chup trong run/e2e/
	cd tests/e2e && VR01_RUN_DIR=../../run VR01_E2E_OUT=../../run/e2e \
	  VR01_UI_URL=https://localhost:$$(grep -s '^INFERENCE_PORT=' ../../deploy/.env | cut -d= -f2 | grep . || echo 8443) \
	  VR01_STOP_BACKEND="$${VR01_STOP_BACKEND-docker stop vr01-mvp-triton-1}" \
	  VR01_START_BACKEND="$${VR01_START_BACKEND-docker start vr01-mvp-triton-1}" node --test ui.e2e.mjs

status:             ## san sang chua, recipe/model nao dang active
	@$(PY) tools/vr01ctl.py --run-dir run status

diag:               ## tao goi chan doan run/diag/vr01-diag-*.tar.gz (khong chua secret, khong chua anh)
	@$(PY) tools/diag_bundle.py --run-dir run

test: build         ## toan bo unit/contract/integration test, chay trong container
	@mkdir -p run
	$(COMPOSE) run --rm --no-deps -w /app/tests init python run_tests.py --output /run-data/test-report-container.json

test-local:         ## nhu tren nhung dung python tren host (can pip install -r backend/requirements.txt)
	cd tests && $(PY) -B run_tests.py --output ../run/test-report.json

digests:            ## in digest image Triton va ID image api de pin vao deploy/.env
	@docker image inspect --format 'TRITON_IMAGE={{index .RepoDigests 0}}' $$(grep -E '^TRITON_IMAGE=' deploy/.env | cut -d= -f2-)
	@docker image inspect --format 'api image id={{.Id}}' vr01-mvp-api:$$(grep -E '^MVP_VERSION=' deploy/.env | cut -d= -f2-)

clean: down         ## XOA du lieu lab trong run/ (ledger, anh, token, chung chi)
	rm -rf run
