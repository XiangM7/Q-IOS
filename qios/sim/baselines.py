from __future__ import annotations

from qios.models import PatchType, TaskRequest, TokenState
from qios.patch_runtime import PatchRuntime
from qios.policy_engine import PolicyEngine
from qios.recovery_engine import RecoveryEngine
from qios.scheduler import Scheduler
from qios.sim.environment import PatchHealth, SimulationEnvironment
from qios.sim.metrics import SimulationMetrics
from qios.structured_job import StructuredJobGenerator
from qios.token_engine import PhiTokenEngine


def _task_is_policy_invalid(task: TaskRequest) -> bool:
    constraints = task.constraints
    return (
        task.priority < 0
        or task.priority > 10
        or bool(constraints.get("force_invalid_patch_hint"))
        or "policy_invalid_reason" in constraints
    )


class BaseSimulationSystem:
    system_name = "base"

    def __init__(self, environment: SimulationEnvironment) -> None:
        self.environment = environment.clone()
        self._baseline_patch_ids = self.environment.baseline_patch_ids()

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        raise NotImplementedError

    def _policy_reject(self, metrics: SimulationMetrics) -> None:
        metrics.record_task(
            latency_ms=0.0,
            completed=False,
            policy_rejected=True,
        )

    def _baseline_patch_for_index(self, index: int) -> str:
        return self._baseline_patch_ids[index % len(self._baseline_patch_ids)]

    def _fixed_primary_patch(self) -> str:
        return self._baseline_patch_ids[0]

    def _attempt_on_patch(self, task: TaskRequest, patch_id: str) -> tuple[bool, float, bool]:
        patch = self.environment.patches[patch_id]
        latency_ms = self.environment.sample_latency_ms(patch_id)
        structural_success = not ("fail" in task.objective.lower())
        env_failure = self.environment.should_inject_failure()
        probability = self.environment.failure_probability(task, patch_id, is_fallback=False)
        if not env_failure:
            env_failure = self.environment._rng.random() < probability
        success = structural_success and not env_failure
        quarantined = self.environment.register_patch_outcome(patch_id, success=success)
        return success, latency_ms, quarantined


class DirectExecutionBaseline(BaseSimulationSystem):
    system_name = "direct"

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        metrics = SimulationMetrics(system_name=self.system_name)
        primary_patch_id = self._fixed_primary_patch()
        for task in tasks:
            if _task_is_policy_invalid(task):
                self._policy_reject(metrics)
                continue

            success, latency_ms, quarantined = self._attempt_on_patch(
                task, primary_patch_id
            )
            metrics.record_task(
                latency_ms=latency_ms,
                completed=success,
                runtime_failed=not success,
                quarantines=1 if quarantined else 0,
            )
        return metrics


class RetryOnlyBaseline(BaseSimulationSystem):
    system_name = "retry_only"

    def __init__(self, environment: SimulationEnvironment, max_retries: int = 2) -> None:
        super().__init__(environment)
        self.max_retries = max_retries

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        metrics = SimulationMetrics(system_name=self.system_name)
        primary_patch_id = self._fixed_primary_patch()
        for task in tasks:
            if _task_is_policy_invalid(task):
                self._policy_reject(metrics)
                continue

            latency_ms = 0.0
            restarts = 0
            quarantines = 0
            completed = False

            for attempt in range(self.max_retries + 1):
                success, attempt_latency, quarantined = self._attempt_on_patch(task, primary_patch_id)
                latency_ms += attempt_latency
                quarantines += 1 if quarantined else 0
                if success:
                    completed = True
                    break
                if attempt < self.max_retries:
                    restarts += 1

            metrics.record_task(
                latency_ms=latency_ms,
                completed=completed,
                runtime_failed=not completed,
                full_restarts=restarts,
                quarantines=quarantines,
            )
        return metrics


class StaticRoutingBaseline(BaseSimulationSystem):
    system_name = "static"

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        metrics = SimulationMetrics(system_name=self.system_name)
        for index, task in enumerate(tasks):
            if _task_is_policy_invalid(task):
                self._policy_reject(metrics)
                continue

            patch_id = self._baseline_patch_for_index(index)
            latency_ms = 0.0
            restarts = 0
            quarantines = 0

            first_success, first_latency, first_quarantine = self._attempt_on_patch(task, patch_id)
            latency_ms += first_latency
            quarantines += 1 if first_quarantine else 0

            completed = first_success
            if not first_success:
                restarts = 1
                second_success, second_latency, second_quarantine = self._attempt_on_patch(task, patch_id)
                latency_ms += second_latency
                quarantines += 1 if second_quarantine else 0
                completed = second_success

            metrics.record_task(
                latency_ms=latency_ms,
                completed=completed,
                runtime_failed=not completed,
                full_restarts=restarts,
                quarantines=quarantines,
            )
        return metrics


class QIOSSimulationSystem(BaseSimulationSystem):
    system_name = "qios"

    def __init__(self, environment: SimulationEnvironment, max_reroutes: int = 1) -> None:
        super().__init__(environment)
        self.max_reroutes = max_reroutes
        self.generator = StructuredJobGenerator()
        self.token_engine = PhiTokenEngine()
        self.policy_engine = PolicyEngine()
        self.scheduler = Scheduler()
        self.recovery_engine = RecoveryEngine()
        self.runtime = PatchRuntime()

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        metrics = SimulationMetrics(system_name=self.system_name)

        for task in tasks:
            task_copy = task.model_copy(deep=True)
            structured_job = self.generator.generate(task_copy)
            token = self.token_engine.create_token(structured_job)

            if task_copy.constraints.get("force_invalid_patch_hint"):
                token.patch_hint = PatchType.ANALYSIS.value
                token.metadata["constraints"] = task_copy.constraints

            admissible, _ = self.policy_engine.check_admissibility(token)
            if not admissible:
                metrics.record_task(
                    latency_ms=0.0,
                    completed=False,
                    policy_rejected=True,
                )
                continue

            self.scheduler.assign_patch(token)

            primary_patch = self._select_primary_patch(token)
            if primary_patch is None:
                metrics.record_task(
                    latency_ms=0.0,
                    completed=False,
                    runtime_failed=True,
                    failed_recovery=True,
                )
                continue

            total_latency_ms = 0.0
            reroutes = 0
            fallback_dispatches = 0
            quarantines = 0
            tried_patch_ids = {primary_patch.patch_id}

            primary_success, primary_latency, primary_quarantine = self._execute_attempt(
                task_copy,
                token,
                primary_patch,
            )
            total_latency_ms += primary_latency
            quarantines += 1 if primary_quarantine else 0

            if primary_success:
                metrics.record_task(
                    latency_ms=total_latency_ms,
                    completed=True,
                    quarantines=quarantines,
                )
                continue

            recovered = False
            failed_recovery = True
            max_reroute_exhausted = False

            while reroutes < self.max_reroutes:
                reroutes += 1
                self.recovery_engine.recover(token, "Simulation recovery reroute triggered.")
                reroute_patch = self._select_recovery_patch(task_copy, token, tried_patch_ids)

                if reroute_patch is None:
                    break

                tried_patch_ids.add(reroute_patch.patch_id)
                if reroute_patch.patch_type == PatchType.FALLBACK.value and task_copy.fallback:
                    fallback_dispatches += 1

                reroute_success, reroute_latency, reroute_quarantine = self._execute_attempt(
                    task_copy,
                    token,
                    reroute_patch,
                )
                total_latency_ms += reroute_latency
                quarantines += 1 if reroute_quarantine else 0

                if reroute_success:
                    recovered = True
                    failed_recovery = False
                    break

            if not recovered and reroutes >= self.max_reroutes and self.max_reroutes > 0:
                max_reroute_exhausted = True

            metrics.record_task(
                latency_ms=total_latency_ms,
                completed=recovered,
                recovered=recovered,
                runtime_failed=not recovered,
                failed_recovery=failed_recovery,
                reroutes=reroutes,
                fallback_dispatches=fallback_dispatches,
                quarantines=quarantines,
                max_reroute_exhausted=max_reroute_exhausted,
            )

        return metrics

    def _select_primary_patch(self, token) -> PatchHealth | None:
        preferred_types = [token.assigned_patch or token.patch_hint or PatchType.ANALYSIS.value]
        patch = self.environment.select_best_patch(
            preferred_types=preferred_types,
            include_quarantined=False,
        )
        if patch is not None:
            return patch
        return self.environment.select_best_patch(
            preferred_types=preferred_types,
            include_quarantined=True,
        )

    def _select_recovery_patch(
        self,
        task: TaskRequest,
        token,
        tried_patch_ids: set[str],
    ) -> PatchHealth | None:
        candidate_types: list[list[str] | None] = []

        if task.fallback:
            candidate_types.append([PatchType.FALLBACK.value])

        if task.constraints.get("sandbox_required"):
            candidate_types.append([PatchType.SANDBOX.value])
        elif token.role == "analysis":
            candidate_types.append([PatchType.ANALYSIS.value])
        else:
            candidate_types.append([PatchType.SANDBOX.value, PatchType.ANALYSIS.value])

        candidate_types.append([PatchType.HUMAN_REVIEW.value, PatchType.ANALYSIS.value, PatchType.SANDBOX.value])
        candidate_types.append(None)

        for preferred_types in candidate_types:
            patch = self.environment.select_best_patch(
                preferred_types=preferred_types,
                exclude_ids=tried_patch_ids,
                include_quarantined=False,
                allow_fallback=bool(task.fallback),
            )
            if patch is not None:
                return patch

        for preferred_types in candidate_types:
            patch = self.environment.select_best_patch(
                preferred_types=preferred_types,
                exclude_ids=None,
                include_quarantined=True,
                allow_fallback=bool(task.fallback),
            )
            if patch is not None:
                return patch

        return None

    def _execute_attempt(
        self,
        task: TaskRequest,
        token,
        patch: PatchHealth,
    ) -> tuple[bool, float, bool]:
        token.assigned_patch = patch.patch_type
        token.patch_hint = patch.patch_type

        runtime_result = self.runtime.execute(token)
        latency_ms = self.environment.sample_latency_ms(patch.patch_id)
        env_failure = self.environment.should_inject_failure()
        if not env_failure:
            env_failure = (
                self.environment._rng.random()
                < self.environment.failure_probability(
                    task,
                    patch.patch_id,
                    is_fallback=patch.patch_type == PatchType.FALLBACK.value,
                )
            )

        success = runtime_result.success and not env_failure
        if not success:
            token.lifecycle_state = TokenState.FAILED

        quarantined = self.environment.register_patch_outcome(
            patch.patch_id,
            success=success,
        )
        return success, latency_ms, quarantined
