"""External publication evidence connectors."""

from postdoc_scout.connectors.base import ConnectorError
from postdoc_scout.connectors.nih_reporter import NIHReporterConnector
from postdoc_scout.connectors.openalex import OpenAlexConnector
from postdoc_scout.connectors.pubmed import PubMedConnector
from postdoc_scout.connectors.semantic_scholar import SemanticScholarConnector

__all__ = [
    "ConnectorError",
    "NIHReporterConnector",
    "OpenAlexConnector",
    "PubMedConnector",
    "SemanticScholarConnector",
]
