"use client";
import { Building2, User, Award, BookOpen } from "lucide-react";
import { Card } from "./ui/card";
import { Badge } from "./ui/badge";
import { Separator } from "./ui/separator";

export type EntityInfo = {
  title: string;
  subtitle?: string;
  dean?: string | null;
  viceDean?: string | null;
  head?: string | null;
  accreditation?: string | null;
  programs?: string[];
};

/** Presentational entity card for faculty/program answers (dean, kaprodi, accreditation). */
export function EntityCard({ info }: { info: EntityInfo }) {
  return (
    <Card className="mt-3 overflow-hidden">
      <div className="flex items-center gap-2.5 border-b border-border bg-accent/40 p-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Building2 className="h-5 w-5" />
        </span>
        <div>
          <div className="text-sm font-semibold text-foreground">{info.title}</div>
          {info.subtitle && <div className="text-xs text-muted-foreground">{info.subtitle}</div>}
        </div>
        {info.accreditation && (
          <Badge variant="success" className="ml-auto"><Award className="h-3 w-3" /> {info.accreditation}</Badge>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 p-3 text-sm">
        {info.dean && <Field icon={<User className="h-3.5 w-3.5" />} label="Dean" value={info.dean} />}
        {info.viceDean && <Field icon={<User className="h-3.5 w-3.5" />} label="Vice Dean" value={info.viceDean} />}
        {info.head && <Field icon={<User className="h-3.5 w-3.5" />} label="Head of Program" value={info.head} />}
      </div>
      {info.programs?.length ? (
        <>
          <Separator />
          <div className="p-3">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <BookOpen className="h-3.5 w-3.5" /> Programs
            </div>
            <div className="flex flex-wrap gap-1.5">
              {info.programs.map((p) => <Badge key={p} variant="secondary">{p}</Badge>)}
            </div>
          </div>
        </>
      ) : null}
    </Card>
  );
}

function Field({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div>
      <div className="flex items-center gap-1 text-xs text-muted-foreground">{icon} {label}</div>
      <div className="font-medium text-foreground">{value}</div>
    </div>
  );
}
