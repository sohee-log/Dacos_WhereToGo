'use client';

// constants.ts에서 분위기(ATMOSPHERES) 데이터를 가져옵니다.
import { ATMOSPHERES } from '../lib/constants';

interface TagGridProps {
  selectedTags: string[];
  onChange: (tags: string[]) => void;
}

export default function TagGrid({ selectedTags, onChange }: TagGridProps) {
  const toggleTag = (tag: string) => {
    if (selectedTags.includes(tag)) {
      onChange(selectedTags.filter((t) => t !== tag));
    } else {
      onChange([...selectedTags, tag]);
    }
  };

  return (
    <div className="grid grid-cols-3 gap-3 p-4 bg-gray-50 rounded-2xl">
      {/* 정의한 10개의 분위기 태그가 화면에 뿌려집니다. */}
      {ATMOSPHERES.map((tag) => {
        const isSelected = selectedTags.includes(tag);
        return (
          <button
            key={tag}
            type="button"
            onClick={() => toggleTag(tag)}
            className={`p-3 rounded-xl border text-sm font-medium transition-all duration-200 active:scale-95 ${
              isSelected
                ? 'bg-blue-600 text-white border-blue-600 shadow-md shadow-blue-100'
                : 'bg-white text-gray-700 border-gray-200 hover:border-gray-300'
            }`}
          >
            #{tag}
          </button>
        );
      })}
    </div>
  );
}