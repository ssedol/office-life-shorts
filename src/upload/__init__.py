"""YouTube 업로드 (명세서 §35-5, DEC-017).

렌더가 끝난 final.mp4를 제목·설명·태그와 함께 올리고, 첫 댓글까지 단다.

명세서 §33-6은 자동 업로드를 MVP 범위 밖으로 뒀으나 운영자 결정으로 범위에 들어왔다.
다만 감사를 통과하지 않은 API 프로젝트의 업로드는 유튜브가 비공개로 잠그므로,
기본 동작은 '비공개로 올려두고 공개 전환은 사람이 누른다'이다.
"""

from .metadata import UploadMetadata, load_metadata
from .youtube import YouTubeUploader

__all__ = ["UploadMetadata", "load_metadata", "YouTubeUploader"]
