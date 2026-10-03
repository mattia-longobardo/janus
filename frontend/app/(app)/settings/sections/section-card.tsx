import { Card } from "@/components/ui";

export function SectionCard({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card className="flex h-full flex-col gap-[18px] px-6 py-[22px]">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-display text-[19px] font-bold">{title}</h2>
        {action}
      </div>
      {children}
    </Card>
  );
}
