interface SectionHeaderProps {
  title: string;
}

export function SectionHeader({ title }: SectionHeaderProps) {
  return (
    <h3 
      className="text-sm font-semibold text-[#1C1C1E] mb-3"
      style={{ fontFamily: 'Inter, sans-serif' }}
    >
      {title}
    </h3>
  );
}
