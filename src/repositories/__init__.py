# -*- coding: utf-8 -*-
"""
===================================
数据访问层模块初始化
===================================

职责：
1. 导出所有 Repository 类
"""

from src.repositories.analysis_repo import AnalysisRepository
from src.repositories.backtest_repo import BacktestRepository
from src.repositories.candidate_pool_repo import CandidatePoolRepository
from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.repositories.decision_signal_outcome_repo import DecisionSignalOutcomeRepository
from src.repositories.experiment_registry_repo import ExperimentRegistryRepository
from src.repositories.oos_consumption_ledger_repo import OOSConsumptionLedgerRepository
from src.repositories.stock_repo import StockRepository
from src.repositories.skill_opinion_sample_repo import SkillOpinionSampleRepository

__all__ = [
    "AnalysisRepository",
    "BacktestRepository",
    "CandidatePoolRepository",
    "DecisionSignalRepository",
    "DecisionSignalOutcomeRepository",
    "ExperimentRegistryRepository",
    "OOSConsumptionLedgerRepository",
    "StockRepository",
    "SkillOpinionSampleRepository",
]
