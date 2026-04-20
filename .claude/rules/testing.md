---
paths:
  - "apps/**/tests/**"
  - "apps/**/*.test.ts"
  - "apps/**/*.test.tsx"
  - "apps/**/test_*.py"
---

# Testing Rules

## TDD を厳守

本プロジェクトは TDD 前提で進める。**実装より先にテストを書け**。
理由：AIエージェントは「明確な合否基準」があると自律修正に入れる。テストがないと LLM は自分の実装を甘めに評価してしまう。

## サイクル

1. **Red**: テストを書いて失敗を確認（期待する振る舞いを明示）
2. **Green**: 最小限の実装でテストを通す
3. **Refactor**: 構造を整える（テストが通り続けることを確認）
4. **検証**: 手動動作確認（Codex レビューはユーザ依頼時のみ実行）

## Frontend (Next.js)

- **Unit**: `vitest` + `@testing-library/react`
- **E2E**: `Playwright`（Phase 1 の 1 つの demo flow のみ必須）
- **視覚回帰**: スコープ外（時間があれば Chromatic 導入）

```typescript
// apps/web/src/components/EvidenceBadge.test.tsx
import { render, screen } from '@testing-library/react';
import { EvidenceBadge } from './EvidenceBadge';

describe('EvidenceBadge', () => {
  it('verified バッジは緑色で表示される', () => {
    render(<EvidenceBadge type="verified" source="Places" />);
    const badge = screen.getByText(/Places/);
    expect(badge).toHaveClass('text-evidence-verified');
  });

  it('estimated バッジは黄色で表示される', () => {
    render(<EvidenceBadge type="estimated" source="LLM" />);
    expect(screen.getByText(/推定/)).toBeInTheDocument();
  });
});
```

## Backend (Flask)

- **Unit**: `pytest` + `pytest-flask`
- **外部 API モック**: `responses`（HTTP）、`vcrpy`（リプレイ）
- **Pydantic スキーマは自動検証**（手動テスト不要）

```python
# apps/api/tests/test_evidence_builder.py
import responses
from src.services.evidence_builder import build_evidence_pack

@responses.activate
def test_build_evidence_pack_from_places():
    responses.add(
        responses.POST,
        "https://places.googleapis.com/v1/places:searchText",
        json={"places": [{"id": "abc123", "displayName": {"text": "箱根湯本駅"}}]}
    )
    pack = build_evidence_pack(query="箱根 温泉", region="神奈川")
    assert len(pack.places) > 0
    assert pack.places[0].place_id == "abc123"

def test_hallucination_detection_rejects_unknown_place_id():
    from src.llm.validator import validate_plan_output
    plan = GeneratedPlan(items=[PlanItem(location=Location(place_id="fake_id"))])
    evidence = EvidencePack(places=[])
    with pytest.raises(HallucinationError):
        validate_plan_output(plan, evidence)
```

## テストファイル配置

- Frontend: コンポーネントと同階層に `.test.tsx`
- Backend: `apps/api/tests/` にミラーリング配置（`src/services/X.py` → `tests/services/test_X.py`）

## カバレッジ目標

- `services/`, `llm/`, `evidence/`: 80% 以上
- `routes/`, `components/`: 60% 以上
- ユーティリティ関数: 90% 以上
- UI の pure なレイアウトコンポーネント: テスト任意

## Do NOT

- 本番 API を叩くテストを書くな（CI で課金される）
- フロントのコンポーネントで LLM を呼ぶテストを書くな（バックのテストに集約）
- `it.skip` や `xit` で失敗テストを放置するな。必ず理由を issue 化してから skip
- テストをパスさせるためだけに実装を歪めるな（「テストが甘い」のサイン）
