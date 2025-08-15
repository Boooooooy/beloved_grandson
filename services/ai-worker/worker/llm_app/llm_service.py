import importlib
import os
import sys
from typing import Any, Dict

# 禁用 CrewAI 遙測功能（避免連接錯誤）
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"

# 兼容「模組方式」與「直接腳本」兩種執行情境
try:
    from .chat_pipeline import AgentManager, handle_user_message
except Exception:
    # 若以腳本模式執行（無封包上下文），把 /app/worker 加進 sys.path
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from llm_app.chat_pipeline import AgentManager, handle_user_message


class LLMService:
    """LLM 微服務接口，負責 Milvus 連接和多用戶會話管理"""

    def __init__(self) -> None:
        self.agent_manager = AgentManager()
        self._milvus_connected = False
        self._user_sessions: Dict[str, Any] = {}  # 為每個用戶維護獨立的 UserSession
        self._ensure_milvus_connection()

    def _ensure_milvus_connection(self):
        """確保 Milvus 連接（長期記憶功能需要）"""
        if self._milvus_connected:
            return

        try:
            from pymilvus import connections

            milvus_uri = os.getenv("MILVUS_URI", "http://localhost:19530")
            connections.connect(alias="default", uri=milvus_uri)
            self._milvus_connected = True
            print("✅ Milvus 連接成功")
        except Exception as e:
            print(f"⚠️  Milvus 連接失敗: {e}")
            print("長期記憶功能可能不可用")

    def _get_or_create_user_session(self, user_id: str):
        """為每個用戶創建獨立的 UserSession（5分鐘超時管理）"""
        if user_id not in self._user_sessions:
            try:
                import threading
                import time

                class UserSession:
                    """用戶會話管理類，負責閒置超時和會話結束處理"""

                    def __init__(self, user_id: str, agent_manager, timeout: int = 300):
                        self.user_id = user_id
                        self.agent_manager = agent_manager
                        self.timeout = timeout
                        self.last_active_time = None
                        self.stop_event = threading.Event()
                        threading.Thread(target=self._watchdog, daemon=True).start()

                    def update_activity(self):
                        import time as _t

                        self.last_active_time = _t.time()

                    def _watchdog(self):
                        import time as _t

                        while not self.stop_event.is_set():
                            _t.sleep(5)
                            if self.last_active_time and (
                                _t.time() - self.last_active_time > self.timeout
                            ):
                                print(f"\n⏳ 閒置超過 {self.timeout}s，開始收尾...")
                                try:
                                    # ---- 統一以封包路徑載入，避免相對匯入失敗 ----
                                    current_dir = os.path.dirname(
                                        os.path.abspath(__file__)
                                    )  # .../llm_app
                                    project_root = os.path.dirname(
                                        current_dir
                                    )  # .../worker
                                    if project_root not in sys.path:
                                        sys.path.insert(0, project_root)

                                    agent_mod = importlib.import_module(
                                        "llm_app.HealthBot.agent"
                                    )
                                    finalize_session = getattr(
                                        agent_mod, "finalize_session", None
                                    )

                                    if finalize_session:
                                        finalize_session(self.user_id)
                                        self.agent_manager.release_health_agent(
                                            self.user_id
                                        )
                                        print(f"✅ 用戶 {self.user_id} 會話已結束")
                                    else:
                                        print(
                                            "⚠️ 找不到 finalize_session()；僅釋放 agent"
                                        )
                                        self.agent_manager.release_health_agent(
                                            self.user_id
                                        )

                                except Exception as e:
                                    print(f"⚠️  會話結束處理錯誤: {e}")
                                    # 至少確保 agent 被釋放
                                    try:
                                        self.agent_manager.release_health_agent(
                                            self.user_id
                                        )
                                    except Exception:
                                        pass
                                self.stop_event.set()

                print(f"🚀 為用戶 {user_id} 創建新會話（5分鐘超時）")
                session = UserSession(user_id, self.agent_manager, timeout=300)
                self._user_sessions[user_id] = session
            except Exception as e:
                print(f"⚠️  無法為 {user_id} 創建會話: {e}")
                print(f"錯誤詳情: {type(e).__name__}: {e}")
                return None

        return self._user_sessions.get(user_id)

    def generate_response(self, task_data: Dict[str, Any]) -> str:
        """生成回應（包含完整長期追蹤功能和獨立用戶會話管理）

        期待的 task_data 欄位對應：
        - patient_id -> 對應 Final 的 user_id
        - text -> 對應 Final 的 query（可選）
        - object_name -> 對應 Final 的 audio_id（可選）
        """
        if not isinstance(task_data, dict):
            return "參數格式錯誤"

        user_id = str(
            task_data.get("patient_id") or task_data.get("user_id") or "unknown_user"
        )
        query = str(task_data.get("text") or "").strip()
        audio_id = None
        # 優先使用 object_name 當 audio_id；若沒有且為純文字則由流程自動以 hash 產生
        if task_data.get("object_name"):
            audio_id = str(task_data.get("object_name"))

        if not query and not audio_id:
            return "缺少必要輸入（text 或 object_name 至少一項）"

        try:
            # 確保 Milvus 連接（長期記憶功能）
            self._ensure_milvus_connection()

            # 為每個用戶創建/獲取獨立會話，並更新活動時間（重置 5 分鐘計時）
            user_session = self._get_or_create_user_session(user_id)
            if user_session:
                user_session.update_activity()  # 重新開始計算 5 分鐘
                print(f"🔄 用戶 {user_id} 活動時間已更新（重置 5 分鐘計時）")

            # 調用對話處理邏輯
            response_text = handle_user_message(
                agent_manager=self.agent_manager,
                user_id=user_id,
                query=query,
                audio_id=audio_id,
                is_final=True,
            )
            return response_text
        except Exception as e:
            print(f"[LLMService] 發生錯誤：{e}")
            return "抱歉，無法生成回應。"

    def finalize_user_session(self, user_id: str):
        """手動結束用戶會話並整理長期記憶（一般由 UserSession 自動處理）"""
        try:
            # ---- 統一以封包路徑載入（避免相對匯入失敗）----
            current_dir = os.path.dirname(os.path.abspath(__file__))  # .../llm_app
            project_root = os.path.dirname(current_dir)  # .../worker
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            agent_mod = importlib.import_module("llm_app.HealthBot.agent")
            finalize_session = getattr(agent_mod, "finalize_session", None)

            # 停止會話監控
            if user_id in self._user_sessions:
                session = self._user_sessions[user_id]
                session.stop_event.set()
                del self._user_sessions[user_id]
                print(f"🛑 已停止用戶 {user_id} 的會話監控")

            # 整理長期記憶並釋放 Agent
            if finalize_session:
                finalize_session(user_id)
            else:
                print("⚠️ 找不到 finalize_session()，僅釋放 agent")
            self.agent_manager.release_health_agent(user_id)
            print(f"✅ 手動結束會話：{user_id}")
        except Exception as e:
            print(f"⚠️  會話結束處理錯誤: {e}")

    def cleanup_all_sessions(self):
        """清理所有用戶會話（用於服務關閉時）"""
        for user_id in list(self._user_sessions.keys()):
            self.finalize_user_session(user_id)

    def get_active_sessions(self):
        """獲取當前活躍的會話列表"""
        return list(self._user_sessions.keys())


def run_interactive_test():
    """互動式測試 - 固定用戶 test_user1，測試 5 分鐘釋放功能"""
    print("🏥 Beloved Grandson LLM Service - 互動測試模式")
    print("=" * 60)
    print("💡 功能說明：")
    print("  - 固定用戶：test_user1")
    print("  - 有輸入時重新開始計算 5 分鐘")
    print("  - 5 分鐘無活動後自動釋放 Agent")
    print("  - 使用 Ctrl+C 退出")
    print("=" * 60)

    # 初始化服務
    llm_service = LLMService()
    user_id = "test_user1"

    print("\n📋 使用說明：")
    print("  - 直接輸入您的訊息")
    print("  - 按 Ctrl+C 退出測試")
    print("=" * 60)

    while True:
        try:
            message = input("\n請輸入您的訊息: ").strip()

            if not message:
                continue

            # 構建 task_data
            task_data = {"patient_id": user_id, "text": message}

            print(f"\n🗣️  輸入：{message}")
            response = llm_service.generate_response(task_data)
            print(f"🤖 AI 回應：{response}")

        except KeyboardInterrupt:
            print("\n\n🔚 收到 Ctrl+C 中斷信號，正在清理...")
            llm_service.cleanup_all_sessions()
            print("👋 再見！")
            break
        except Exception as e:
            print(f"❌ 發生錯誤：{e}")


if __name__ == "__main__":
    # 載入環境變數
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    # 建議以模組模式執行，確保封包路徑正確：
    #   python -m llm_app.llm_service
    run_interactive_test()
    # 測試 LLMService
    # 0. .env.example 改成 .env ，可以不做任何設定
    # 1. 啟動ai-worker和相關的容器
    # docker-compose -f docker-compose.dev.yml up -d --build ai-worker

    # 2. 執行測試腳本
    # docker-compose -f docker-compose.dev.yml exec ai-worker python worker/llm_app/llm_service.py

    #! task_data： LLM RAG 需要什麼內容，請找做後端的人要，後端會處理並將資料放置在task_data裡面
