from odoo import fields, http
from odoo.exceptions import AccessError
from odoo.http import request
from werkzeug.exceptions import NotFound


class KabayNoticePortal(http.Controller):
    @staticmethod
    def _require_portal():
        if not request.env.user.has_group("base.group_portal"):
            raise NotFound()

    @http.route("/my/kabay/notices", type="http", auth="user", website=True, methods=["GET"])
    def notices(self, filter="all", **kwargs):
        self._require_portal()
        allowed_filters = {"all", "unread", "read", "important", "urgent"}
        filter_by = filter if filter in allowed_filters else "all"
        now = fields.Datetime.now()
        domain = [
            ("state", "=", "published"), ("publish_datetime", "<=", now),
            "|", ("expiration_datetime", "=", False), ("expiration_datetime", ">=", now),
        ]
        if filter_by == "important":
            domain.append(("priority", "in", ["important", "urgent"]))
        elif filter_by == "urgent":
            domain.append(("priority", "=", "urgent"))
        records = request.env["kabay.notice"].search(domain, order="publish_datetime desc, id desc", limit=100)
        visible = request.env["kabay.notice"]
        for notice in records:
            try:
                notice._portal_check_access()
                visible |= notice
            except AccessError:
                continue
        records = visible
        receipts = request.env["kabay.notice.read"].search([("notice_id", "in", records.ids)])
        read_notice_ids = set(receipts.mapped("notice_id").ids)
        if filter_by == "read":
            records = records.filtered(lambda notice: notice.id in read_notice_ids)
        elif filter_by == "unread":
            records = records.filtered(lambda notice: notice.id not in read_notice_ids)
        items = [{
            "notice": notice,
            "unread": notice.id not in read_notice_ids,
            "type_label": dict(notice._fields["notice_type"].selection).get(notice.notice_type),
            "priority_label": dict(notice._fields["priority"].selection).get(notice.priority),
        } for notice in records]
        return request.render("kabay_notices.portal_notice_list", {"notices": items, "filter_by": filter_by})

    @http.route("/my/kabay/notices/<int:notice_id>", type="http", auth="user", website=True, methods=["GET"])
    def notice_detail(self, notice_id, **kwargs):
        self._require_portal()
        notice = request.env["kabay.notice"].browse(notice_id).exists()
        if not notice:
            raise NotFound()
        try:
            notice._portal_check_access()
            if notice.publish_datetime > fields.Datetime.now():
                raise AccessError("Aviso aún no publicado")
            notice.action_mark_read()
            documents = notice.document_ids
        except AccessError:
            raise NotFound()
        return request.render("kabay_notices.portal_notice_detail", {
            "notice": notice,
            "documents": documents,
            "type_label": dict(notice._fields["notice_type"].selection).get(notice.notice_type),
            "priority_label": dict(notice._fields["priority"].selection).get(notice.priority),
        })
