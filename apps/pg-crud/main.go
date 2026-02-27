// pg-crud: PostgreSQL CRUD 데모 앱 (Go / net/http + pgx)
//
// 백그라운드 워커: 주기적으로 레코드 삽입 → 조회 → 랜덤 삭제 반복
// Valkey pub/sub: CRUD 이벤트 PUBLISH (채널: crud-events)
// 미션 모드: 환경변수 MISSION 으로 트러블슈팅 시나리오 주입
//
// 연결 정보 (환경변수)
//
//	PG_DSN      : host=... port=5432 user=... password=... dbname=demo sslmode=disable
//	VALKEY_HOST : valkey-production.middleware.svc.cluster.local
//	VALKEY_PORT : 6379
//	VALKEY_PASSWORD : (선택) auth.enabled 시 필수
//	MISSION     : "" | wrong-creds | oom | slow-query
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

// ---------------------------------------------------------------------------
// 설정
// ---------------------------------------------------------------------------
var (
	pgDSN          = getenv("PG_DSN", "host=localhost port=5432 user=postgres password=postgres dbname=demo sslmode=disable")
	valkeyHost     = getenv("VALKEY_HOST", "localhost")
	valkeyPort     = getenv("VALKEY_PORT", "6379")
	valkeyPassword = getenv("VALKEY_PASSWORD", "")
	mission        = getenv("MISSION", "")
	workerInterval = getDurationEnv("WORKER_INTERVAL", 5*time.Second)
)

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getDurationEnv(key string, def time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return time.Duration(n) * time.Second
		}
	}
	return def
}

// ---------------------------------------------------------------------------
// 글로벌
// ---------------------------------------------------------------------------
var (
	pool   *pgxpool.Pool
	rdb    *redis.Client
)

// ---------------------------------------------------------------------------
// 이벤트 발행
// ---------------------------------------------------------------------------
type Event struct {
	Source  string      `json:"source"`
	Action  string      `json:"action"`
	Payload interface{} `json:"payload"`
	Ts      string      `json:"ts"`
}

func publishEvent(action string, payload interface{}) {
	evt := Event{
		Source:  "pg-crud",
		Action:  action,
		Payload: payload,
		Ts:      time.Now().UTC().Format(time.RFC3339),
	}
	b, _ := json.Marshal(evt)
	if err := rdb.Publish(context.Background(), "crud-events", string(b)).Err(); err != nil {
		log.Printf("[WARN] Valkey publish: %v", err)
	}
}

// ---------------------------------------------------------------------------
// DB 초기화
// ---------------------------------------------------------------------------
func initDB(ctx context.Context) error {
	dsn := pgDSN
	if mission == "wrong-creds" {
		dsn = strings.ReplaceAll(dsn, "password=", "password=BADPASSWORD")
	}

	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return err
	}
	if mission == "conn-exhaust" {
		cfg.MaxConns = 1
	}

	pool, err = pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return err
	}
	if err := pool.Ping(ctx); err != nil {
		return fmt.Errorf("ping failed: %w", err)
	}

	_, err = pool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS records (
			id SERIAL PRIMARY KEY,
			name TEXT NOT NULL,
			value TEXT,
			created_at TIMESTAMPTZ DEFAULT now()
		)`)
	return err
}

// ---------------------------------------------------------------------------
// 백그라운드 워커
// ---------------------------------------------------------------------------
func backgroundWorker(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case <-time.After(workerInterval):
		}

		// MISSION: oom → 대형 슬라이스 반복 할당
		if mission == "oom" {
			buf := make([]byte, 100*1024*1024) // 100MB
			_ = buf
		}

		name := fmt.Sprintf("rec-%s", randStr(6))
		var id int
		var query string
		if mission == "slow-query" {
			// pg_sleep 으로 느린 쿼리 유발
			query = fmt.Sprintf("INSERT INTO records(name,value) SELECT '%s', pg_sleep(5)::text RETURNING id", name)
		} else {
			query = fmt.Sprintf("INSERT INTO records(name,value) VALUES('%s','%d') RETURNING id", name, time.Now().UnixMilli())
		}
		row := pool.QueryRow(ctx, query)
		if err := row.Scan(&id); err != nil {
			log.Printf("[ERROR] insert: %v", err)
			continue
		}
		publishEvent("insert", map[string]interface{}{"id": id, "name": name})

		// 랜덤 삭제
		var delID int
		err := pool.QueryRow(ctx, "SELECT id FROM records ORDER BY random() LIMIT 1").Scan(&delID)
		if err == nil {
			pool.Exec(ctx, "DELETE FROM records WHERE id=$1", delID)
			publishEvent("delete", map[string]interface{}{"id": delID})
		}

		var count int
		pool.QueryRow(ctx, "SELECT count(*) FROM records").Scan(&count)
		log.Printf("[worker] insert+delete done. total=%d", count)
	}
}

func randStr(n int) string {
	const letters = "abcdefghijklmnopqrstuvwxyz"
	b := make([]byte, n)
	for i := range b {
		b[i] = letters[rand.Intn(len(letters))]
	}
	return string(b)
}

// ---------------------------------------------------------------------------
// HTTP 핸들러
// ---------------------------------------------------------------------------
func healthHandler(w http.ResponseWriter, r *http.Request) {
	json.NewEncoder(w).Encode(map[string]string{"status": "ok", "mission": mission})
}

func listRecordsHandler(w http.ResponseWriter, r *http.Request) {
	rows, err := pool.Query(r.Context(), "SELECT id, name, value, created_at FROM records ORDER BY id DESC LIMIT 20")
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	defer rows.Close()

	type Record struct {
		ID        int       `json:"id"`
		Name      string    `json:"name"`
		Value     string    `json:"value"`
		CreatedAt time.Time `json:"created_at"`
	}
	var records []Record
	for rows.Next() {
		var rec Record
		rows.Scan(&rec.ID, &rec.Name, &rec.Value, &rec.CreatedAt)
		records = append(records, rec)
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(records)
}

func createRecordHandler(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Name  string `json:"name"`
		Value string `json:"value"`
	}
	json.NewDecoder(r.Body).Decode(&body)
	if body.Name == "" {
		body.Name = "item-" + randStr(4)
	}
	var id int
	err := pool.QueryRow(r.Context(), "INSERT INTO records(name,value) VALUES($1,$2) RETURNING id", body.Name, body.Value).Scan(&id)
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	publishEvent("insert", map[string]interface{}{"id": id, "name": body.Name})
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(201)
	json.NewEncoder(w).Encode(map[string]int{"id": id})
}

func deleteRecordHandler(w http.ResponseWriter, r *http.Request) {
	idStr := strings.TrimPrefix(r.URL.Path, "/records/")
	_, err := pool.Exec(r.Context(), "DELETE FROM records WHERE id=$1", idStr)
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	publishEvent("delete", map[string]string{"id": idStr})
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"deleted": idStr})
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------
func main() {
	ctx := context.Background()

	// Valkey
	opts := &redis.Options{Addr: valkeyHost + ":" + valkeyPort}
	if valkeyPassword != "" {
		opts.Password = valkeyPassword
	}
	rdb = redis.NewClient(opts)

	// PostgreSQL
	if err := initDB(ctx); err != nil {
		log.Fatalf("[FATAL] DB init failed: %v", err)
	}
	log.Printf("[INFO] PostgreSQL connected. MISSION=%q", mission)

	go backgroundWorker(ctx)

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", healthHandler)
	mux.HandleFunc("/records", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			listRecordsHandler(w, r)
		case http.MethodPost:
			createRecordHandler(w, r)
		default:
			http.Error(w, "method not allowed", 405)
		}
	})
	mux.HandleFunc("/records/", deleteRecordHandler)

	log.Printf("[INFO] pg-crud listening on :8080")
	log.Fatal(http.ListenAndServe(":8080", mux))
}
