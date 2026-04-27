interface SectionHeaderProps {
  title: string;
}

export function SectionHeader({ title }: SectionHeaderProps) {
  return (
    <h3 
      className="section-title"
    >
      {title}
    </h3>
  );
}
