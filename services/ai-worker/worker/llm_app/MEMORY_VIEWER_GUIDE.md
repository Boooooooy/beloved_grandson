# 記憶資料管理工具 - 使用指南

## 🎯 功能說明

這個工具用於查看和管理 Beloved Grandson 系統中的用戶資料：
- **Milvus**: 用戶長期記憶 (user_memory collection)
- **Redis**: 會話資料、音頻緩衝、警報等

## 🚀 正確使用方式

### 方案 1: 在 Docker 容器內運行 (推薦)

```bash
# 1. 確保所有服務運行
docker-compose -f docker-compose.dev.yml up -d

# 2. 進入 ai-worker 容器
docker-compose -f docker-compose.dev.yml exec ai-worker bash

# 3. 運行工具
python worker/llm_app/view_memory_data.py
```

### 方案 2: 本地運行 (需要設定)

如果要在本地運行，需要設定環境變數：

```bash
# 設定連接資訊
export MILVUS_URI="http://localhost:19530"
export REDIS_URL="redis://localhost:6379/0"

# 運行工具
python view_memory_data.py
```

## 🔧 故障排除

### 連接問題診斷

1. **檢查服務狀態**:
   ```bash
   docker-compose -f docker-compose.dev.yml ps
   ```

2. **檢查網路連接**:
   ```bash
   # 檢查 Milvus
   curl http://localhost:19530
   
   # 檢查 Redis
   redis-cli ping
   ```

3. **查看日誌**:
   ```bash
   docker-compose -f docker-compose.dev.yml logs milvus
   docker-compose -f docker-compose.dev.yml logs redis
   ```

### 常見錯誤解決

| 錯誤 | 原因 | 解決方案 |
|------|------|----------|
| `Fail connecting to server on milvus:19530` | 不在 Docker 網路內 | 使用容器內運行 |
| `Error 10061 connecting to localhost:6379` | Redis 未啟動 | `docker-compose up -d redis` |
| `Collection user_memory not found` | 資料庫未初始化 | 先運行一次對話產生資料 |

## 🎮 工具功能

### 主選單選項

1. **系統概覽**: 查看整體資料統計
2. **用戶管理**: 查看/刪除特定用戶的所有資料
3. **資料瀏覽**: 分別瀏覽 Milvus 或 Redis 資料
4. **連接測試**: 測試並重新連接服務

### 資料類型說明

#### Milvus (user_memory)
- `id`: 自動生成的主鍵
- `user_id`: 用戶識別碼
- `updated_at`: 更新時間戳 (毫秒)
- `text`: 記憶文本內容
- `embedding`: 向量表示 (1536維)

#### Redis 鍵值模式
- `session:{user_id}:*`: 會話相關資料
  - `state`: 會話狀態
  - `history`: 對話歷史
  - `summary:text`: 摘要文本
  - `summary:rounds`: 摘要輪數
  - `alerts`: 警報記錄

- `audio:{user_id}:*`: 音頻相關資料
  - `buf`: 音頻緩衝
  - `result`: 處理結果

- `processed:{user_id}:*`: 已處理請求記錄
- `lock:audio:*`: 音頻處理鎖
- `alerts:stream`: 系統警報流

## ⚠️ 安全注意事項

1. **刪除確認**: 刪除資料需要輸入 'DELETE' 確認
2. **備份建議**: 重要資料建議先備份
3. **權限控制**: 僅限開發和運維人員使用
4. **日誌記錄**: 所有操作都會記錄在終端

## 📞 支援

如果遇到問題：
1. 先使用工具內的「連接測試」功能
2. 檢查 Docker 容器狀態
3. 查看相關服務日誌
4. 確認環境變數設定

---

**開發團隊**: Beloved Grandson AI Team  
**最後更新**: 2024
