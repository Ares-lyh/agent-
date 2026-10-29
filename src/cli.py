"""CLI entry points for the Music Creator Agent System."""
import sys
import os
import json

# Prevent UnicodeEncodeError on Windows terminals with non-UTF8 encoding (e.g., GBK/cp936)
if sys.platform == "win32":
    try:
        if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import click
from src.agents.master_agent import MasterAgent
from src.core.checkpoint import CheckpointManager
from src.core.state_machine import ProjectState
from src.config import settings


@click.group()
def cli():
    """音乐创作主 Agent 系统命令行工具 (Music Creator Agent CLI)"""
    pass


@cli.command("run")
@click.option("--brief", "-b", required=True, type=click.Path(exists=True), help="歌曲制作需求单 brief 文件路径 (JSON)")
def run_command(brief: str):
    """读取歌曲需求单 (brief) 并启动音乐创作 Agent 流水线"""
    click.secho(f"\n🎵 [启动 Agent] 正在读取歌曲需求单: {brief} ...", fg="cyan", bold=True)
    master = MasterAgent()
    try:
        checkpoint, task_plan, lyrics = master.start_from_brief_file(brief)
        click.secho(f"✅ 项目初始化成功! 项目 ID: [{checkpoint.project_id}]", fg="green", bold=True)
        click.secho(f"📋 歌曲计划: 《{lyrics.title}》 | 曲风: {task_plan.genre} | 情绪: {task_plan.mood}", fg="yellow")
        
        # Display anomalies if any
        if checkpoint.detected_anomalies:
            click.secho("\n⚠️ [需求单异常与冲突预警]:", fg="yellow", bold=True)
            for a in checkpoint.detected_anomalies:
                click.secho(f"  - [{a.get('issue_type')}] {a.get('field')}: {a.get('message')}", fg="yellow")

        click.secho("\n📝 [歌词初稿已就绪]:", fg="cyan", bold=True)
        click.echo(lyrics.to_markdown())

        if checkpoint.state == ProjectState.LYRICS_READY:
            click.secho(f"\n🔒 当前状态: [{checkpoint.state.value}] - 等待人工审核歌词", fg="magenta", bold=True)
            click.secho("👉 请审查歌词后执行以下命令进行审核批准或打回修改:", fg="white")
            click.secho(f"   批准: python -m src.cli approve --project {checkpoint.project_id} --stage lyrics", fg="green")
            click.secho(f"   打回: python -m src.cli approve --project {checkpoint.project_id} --stage lyrics --reject --feedback \"调整副歌情绪\"", fg="red")
        elif checkpoint.state == ProjectState.LYRICS_APPROVED:
            click.secho(f"\n🔒 当前状态: [{checkpoint.state.value}] - 歌词已审核批准", fg="magenta", bold=True)
            click.secho("👉 请执行 resume 命令进入作曲与音频生成阶段:", fg="white")
            click.secho(f"   继续: python -m src.cli resume {checkpoint.project_id}", fg="green")
        elif checkpoint.state == ProjectState.AUDIO_READY:
            click.secho(f"\n🔒 当前状态: [{checkpoint.state.value}] - 音频已生成，等待人工试听审核", fg="magenta", bold=True)
            click.secho("👉 请试听后执行以下命令进行审核批准或打回修改:", fg="white")
            click.secho(f"   批准: python -m src.cli approve --project {checkpoint.project_id} --stage audio", fg="green")
            click.secho(f"   打回: python -m src.cli approve --project {checkpoint.project_id} --stage audio --reject --feedback \"调整编曲\"", fg="red")
        elif checkpoint.state == ProjectState.AUDIO_APPROVED:
            click.secho(f"\n🔒 当前状态: [{checkpoint.state.value}] - 音频已审核批准", fg="magenta", bold=True)
            click.secho("👉 请执行 export 命令构建发行物料包:", fg="white")
            click.secho(f"   导出: python -m src.cli export --project {checkpoint.project_id}", fg="green")
        else:
            click.secho(f"\n🎉 当前状态: [{checkpoint.state.value}] - 项目流程已完结", fg="green", bold=True)
            click.secho(f"👉 可通过 status 查询详情或 export 重新导出物料包:", fg="white")
            click.secho(f"   查看: python -m src.cli status {checkpoint.project_id}", fg="cyan")
            click.secho(f"   导出: python -m src.cli export --project {checkpoint.project_id}", fg="green")
    except Exception as e:
        click.secho(f"❌ 运行失败: {str(e)}", fg="red", err=True)
        sys.exit(1)


@cli.command("status")
@click.argument("project_id", required=True)
def status_command(project_id: str):
    """查询指定项目的当前运行状态与产物详情"""
    mgr = CheckpointManager(settings.BASE_STORAGE_DIR)
    if not mgr.project_exists(project_id):
        click.secho(f"❌ 未找到项目 [{project_id}] 的运行记录", fg="red", err=True)
        sys.exit(1)

    checkpoint = mgr.load_checkpoint(project_id)
    project_dir = mgr.get_project_dir(project_id)

    click.secho(f"\n📊 项目运行状态看板 - ID: [{project_id}]", fg="cyan", bold=True)
    click.secho(f"   - 生命周期状态: {checkpoint.state.value}", fg="green" if "ready" in checkpoint.state.value or "approved" in checkpoint.state.value else "yellow", bold=True)
    click.secho(f"   - 歌词当前版本: {checkpoint.lyrics_version}")
    click.secho(f"   - 音频当前版本: {checkpoint.audio_version}")
    click.secho(f"   - 已完成阶段: {', '.join(checkpoint.completed_stages)}")
    click.secho(f"   - 最后更新时间: {checkpoint.updated_at}")

    # Check approvals
    approvals_path = os.path.join(project_dir, "approvals.json")
    if os.path.exists(approvals_path):
        with open(approvals_path, "r", encoding="utf-8") as f:
            app_data = json.load(f)
            click.secho(f"   - 审核记录: {len(app_data.get('records', []))} 条记录")
            for r in app_data.get("records", []):
                verdict = "✅ 批准" if r.get("approved") else "❌ 拒绝/重修"
                click.secho(f"     • 阶段 [{r.get('stage')}]: {verdict} ({r.get('reviewer')}) - {r.get('feedback')}")

    if checkpoint.detected_anomalies:
        click.secho(f"   - 异常标记数: {len(checkpoint.detected_anomalies)} 项", fg="yellow")

    click.secho(f"   - 本地工作区目录: {project_dir}\n")


@cli.command("approve")
@click.option("--project", "-p", "project_id", required=True, help="项目 ID")
@click.option("--stage", "-s", required=True, type=click.Choice(["lyrics", "audio"]), help="审核阶段: lyrics 或 audio")
@click.option("--reject", is_flag=True, default=False, help="标记为拒绝打回修改")
@click.option("--feedback", "-f", default=None, help="审核意见与修改批注")
@click.option("--reviewer", default="Human Reviewer", help="审核人标识")
def approve_command(project_id: str, stage: str, reject: bool, feedback: str, reviewer: str):
    """对指定阶段（歌词/音频）执行人工审核批准或驳回"""
    master = MasterAgent()
    try:
        approved = not reject
        action_text = "驳回修改" if reject else "审核批准"
        click.secho(f"\n🔍 正在对项目 [{project_id}] 的 [{stage}] 阶段执行 {action_text} ...", fg="cyan")
        
        checkpoint = master.approve_stage(
            project_id=project_id,
            stage=stage,
            approved=approved,
            feedback=feedback,
            reviewer=reviewer,
        )

        if approved:
            click.secho(f"✅ [{stage}] 阶段审核批准通过！当前状态: [{checkpoint.state.value}]", fg="green", bold=True)
            if stage == "lyrics":
                click.secho(f"👉 下一步：请执行 resume 指令启动作曲与音频生成:", fg="white")
                click.secho(f"   python -m src.cli resume {project_id}", fg="yellow", bold=True)
            elif stage == "audio":
                click.secho(f"👉 下一步：音频已批准，请执行 export 指令构建发行物料包:", fg="white")
                click.secho(f"   python -m src.cli export --project {project_id}", fg="yellow", bold=True)
        else:
            click.secho(f"⚠️ [{stage}] 阶段已打回修改，已自动自增版本重新生成！当前状态: [{checkpoint.state.value}]", fg="yellow", bold=True)
    except Exception as e:
        click.secho(f"❌ 审核操作失败: {str(e)}", fg="red", err=True)
        sys.exit(1)


@cli.command("resume")
@click.argument("project_id", required=True)
def resume_command(project_id: str):
    """中断或崩溃后从断点继续恢复执行流水线"""
    click.secho(f"\n🔄 正在从 checkpoint 恢复项目 [{project_id}] 的执行链路 ...", fg="cyan", bold=True)
    master = MasterAgent()
    try:
        checkpoint, message = master.resume(project_id)
        click.secho(f"✅ 执行进度已推进: {message}", fg="green", bold=True)
        click.secho(f"📌 当前生命周期状态: [{checkpoint.state.value}]", fg="yellow")
    except Exception as e:
        click.secho(f"❌ 恢复失败: {str(e)}", fg="red", err=True)
        sys.exit(1)


@cli.command("export")
@click.option("--project", "-p", "project_id", required=True, help="项目 ID")
@click.option("--out", "-o", "out_dir", default=None, help="导出物料包目录 (默认 release-package/)")
def export_command(project_id: str, out_dir: str):
    """导出本地发行物料包（只生成本地发行物料包，严禁调用发布平台）"""
    click.secho(f"\n📦 正在为项目 [{project_id}] 构建与导出发行物料包 ...", fg="cyan", bold=True)
    master = MasterAgent()
    try:
        manifest, pkg_dir = master.export_package(project_id, target_dir=out_dir)
        status_color = "green" if manifest.package_status == "ready" else "yellow"
        click.secho(f"\n🎉 物料包导出完成！路径: {pkg_dir}", fg="green", bold=True)
        click.secho(f"📄 物料包判定状态: [{manifest.package_status}]", fg=status_color, bold=True)
        click.secho(f"🎵 歌曲标题: 《{manifest.song_title}》 | 艺人: {manifest.artist_name}")
        click.secho(f"🔐 原始 Brief 哈希: {manifest.brief_hash}")
        click.secho(f"🎧 音频文件: {manifest.audio_file.file_name} (SHA-256: {manifest.audio_file.sha256[:16]}...)")
        
        if manifest.missing_materials:
            click.secho("\n⚠️ [物料缺失清单 (状态已降级为 needs_info)]:", fg="yellow", bold=True)
            for m in manifest.missing_materials:
                click.secho(f"   • {m}", fg="yellow")

        if manifest.integrity_issues:
            click.secho("\n❌ [完整性异常]:", fg="red", bold=True)
            for i in manifest.integrity_issues:
                click.secho(f"   • {i}", fg="red")

        click.secho(f"\n📋 运行报告已同步更新至本地工作区 run_report.md", fg="white")
    except Exception as e:
        click.secho(f"❌ 导出物料包失败: {str(e)}", fg="red", err=True)
        sys.exit(1)


@cli.command("rights")
@click.option("--project", "project_id", required=True)
@click.option("--artist", required=True)
@click.option("--statement", required=True)
@click.option("--confirm", is_flag=True, required=True, help="确认已审查版权与采样授权声明")
def rights_command(project_id, artist, statement, confirm):
    """补齐人工确认的版权声明与署名，再执行 export 重新校验。"""
    from src.core.graph import brief_digest
    from src.utils.persistence import atomic_write, project_lock
    master = MasterAgent()
    folder = master.checkpoint_manager.get_project_dir(project_id)
    with project_lock(folder):
        brief = master._load_brief(project_id)
        brief.artist_name = artist
        brief.copyright_statement = statement
        brief.rights_confirmed = confirm
        master.graph_engine.update_metadata(project_id,brief,"RIGHTS","已确认版权声明和署名")
    click.echo("版权信息已保存，请执行 export 重新校验封包")


@cli.command("serve")
@click.option("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
@click.option("--port", "-p", default=8000, type=int, help="监听端口 (默认 8000)")
def serve_command(host: str, port: int):
    """启动轻量 Web GUI 试听与审批工作台"""
    import uvicorn
    click.secho(f"\n🚀 正在启动音乐创作主 Agent 协同工作台 (Web Studio)...", fg="cyan", bold=True)
    click.secho(f"🌐 本地访问地址: http://{host}:{port}", fg="green", bold=True)
    click.secho(f"👉 按 Ctrl+C 可安全终止服务\n", fg="white")
    uvicorn.run("src.web.app:app", host=host, port=port, reload=False)


def main():
    cli()


if __name__ == "__main__":
    main()
