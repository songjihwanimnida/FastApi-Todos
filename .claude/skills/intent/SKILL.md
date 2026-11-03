---
name: intent
description: 새 기능·변경 아이디어를 팀 템플릿에 맞춘 intent.md로 정리한다. 사용자가 /intent 를 입력하거나 "intent.md 써줘"라고 할 때 사용.
---

# intent.md 작성 (팀 합의 템플릿)

AI-native SDLC 1단계(Plan)의 아티팩트를 만든다. 코드는 읽기만 하고 수정하지 않는다.

## 진행
1. 사용자가 자기 말로 설명한 아이디어를 읽는다. 관련 코드를 빠르게 훑어 현재 상태를 파악한다.
2. 분석가가 물을 질문을 **한 번에 최대 3개**만 묻는다: 범위(넣을 것/뺄 것), 영향받는 사용자, 제약 조건, 성공의 모습.
3. 답을 받으면 `intent/<짧은-영문-slug>/intent.md` 를 아래 템플릿으로 작성한다. 사용자의 표현을 최대한 살린다.
4. 잘못 이해한 부분이 있는지 묻고, 수정 요청이 있으면 반영한다. 커밋은 사용자가 승인한 뒤에 한다.

## 템플릿
```markdown
# Intent: <기능 이름>
Author: <작성자>. Date: <YYYY-MM-DD>. Status: draft.

## Problem
<지금 무엇을 못 하는지, 누가 불편한지>

## Proposed outcome
<더 나은 상태가 어떤 모습인지>

## Out of scope
<이번에 하지 않는 것>

## Affected users and systems
<사용자, 파일/모듈, API>

## Constraints
<지켜야 할 조건>

## Open questions
<아직 답이 없는 질문>
```

한 페이지를 넘기지 않는다. 구현 방법(어떤 함수를 바꿀지)은 쓰지 않는다. 그건 spec.md와 plan.md의 몫이다.
