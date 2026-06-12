import React, { createContext, useContext, useState } from 'react'

// Deep merge: base + overrides (only top-level sections merged)
function m(base, ov) {
  const out = {}
  for (const k of Object.keys(base)) {
    if (ov[k] && typeof base[k] === 'object' && !Array.isArray(base[k])) {
      out[k] = { ...base[k], ...ov[k] }
    } else if (ov[k] !== undefined) {
      out[k] = ov[k]
    } else {
      out[k] = base[k]
    }
  }
  return out
}

const EN = {
  rtl: false, langName: 'English', flag: '🇺🇸',
  tagline: 'Your AI Workforce for Business Growth™',
  live: 'Live', reconnecting: 'Reconnecting…',
  tabs: { home:'🏠 Home', dashboard:'📊 Dashboard', callCenter:'🎧 Call Center', businesses:'🏢 CRM & Sales', appointments:'📅 Appointments', ai:'🤖 AI Analyzer' },
  home: { book:'Book Appointment', viewDash:'View Dashboard', heroTag:'— YOUR AI WORKFORCE FOR BUSINESS GROWTH™ —', comingSoon:'Coming Soon', comingSoonSub:'This module is under development and will be available in the next release.', back:'← Back to Home' },
  trust: ['ALL-IN-ONE PLATFORM','AI POWERED','HUMAN APPROVED','RESULTS DRIVEN','SECURE & RELIABLE'],
  features: [
    { name:'AI CALL CENTER',    desc:'Smart Conversations. Better Customer Experiences.' },
    { name:'APPOINTMENTS',      desc:'Schedule. Manage. Never Miss.' },
    { name:'WEBSITE BUILDER',   desc:'Build. Launch. Grow Online.' },
    { name:'MARKETING & SEO',   desc:'Get Found. Get Leads. Grow Faster.' },
    { name:'CONTENT STUDIO',    desc:'Videos. Reels. Graphics. AI Powered.' },
    { name:'CRM & SALES',       desc:'Leads to Loyal Customers.' },
    { name:'ANALYTICS',         desc:'Insights. Reports. Smarter Decisions.' },
    { name:'AUTOMATION',        desc:'Workflows That Work. Save Time. Scale More.' },
  ],
  c: { save:'Save', cancel:'Cancel', edit:'Edit', delete:'Delete', add:'Add', new:'New', search:'Search…', loading:'Loading…', back:'Back', name:'Name', email:'Email', phone:'Phone', notes:'Notes', status:'Status', date:'Date', time:'Time', actions:'Actions', noData:'No data yet.', all:'All', confirm:'Confirm', complete:'Complete', selectBiz:'Select a business…' },
  call: { newCall:'New Call', dial:'📞 Dial', end:'⏹ End Call', answer:'📞 Answer', decline:'📵 Decline', micOn:'🎙 Mic On', micOff:'🎙 Mic Off', live:'LIVE CALL', transcript:'Live Transcript', aiAssist:'AI Assist', ringing:'Ringing…', connecting:'Connecting…', callerName:'Caller Name', reason:'Reason for Call', today:"Today's Calls", total:'Total Logged', urgent:'Urgent Flagged', ready:'⬤ Ready', noHistory:'No call history yet.', duration:'Duration', triage:'Triage', sentiment:'Sentiment', analyzing:'⏳ AI analyzing…', analysisReady:'✅ Analysis ready', typeHint:'Type 30+ characters to trigger AI' },
  biz: { title:'Businesses / CRM', addNew:'+ Add Business', bizName:'Business Name', industry:'Industry', revenue:'Revenue ($)', employees:'Employees', noData:'No businesses yet. Add your first one!' },
  appt: { title:'Appointments', addNew:'+ New Appointment', business:'Business', service:'Service', custName:'Customer Name', custPhone:'Customer Phone', scheduled:'Scheduled', confirmed:'Confirmed', completed:'Completed', noData:'No appointments yet.', quickAdd:'+ Quick Add Business' },
  ai: { title:'AI Transcript Analyzer', placeholder:'Paste call transcript here…', analyze:'🧠 Analyze', analyzing:'⏳ Analyzing…', summary:'Summary', actionItems:'Action Items', noResult:'Paste a transcript and click Analyze.' },
  dash: { title:'Dashboard', businesses:'Businesses', appointments:'Appointments', calls:"Today's Calls" },
}

// ── Spanish ──────────────────────────────────────────────────────────────────
const ES = m(EN, {
  rtl:false, langName:'Español', flag:'🇲🇽',
  tagline:'Tu Fuerza Laboral IA para el Crecimiento Empresarial™',
  live:'En Vivo', reconnecting:'Reconectando…',
  tabs:{ home:'🏠 Inicio', dashboard:'📊 Tablero', callCenter:'🎧 Call Center', businesses:'🏢 CRM y Ventas', appointments:'📅 Citas', ai:'🤖 Analizador IA' },
  home:{ book:'Reservar Cita', viewDash:'Ver Tablero', heroTag:'— TU FUERZA LABORAL IA PARA CRECER™ —', comingSoon:'Próximamente', comingSoonSub:'Este módulo está en desarrollo y estará disponible en la próxima versión.', back:'← Volver al Inicio' },
  trust:['PLATAFORMA TODO-EN-UNO','POTENCIADO POR IA','APROBADO POR HUMANOS','ORIENTADO A RESULTADOS','SEGURO Y CONFIABLE'],
  features:[
    { name:'CENTRO DE LLAMADAS IA', desc:'Conversaciones Inteligentes. Mejores Experiencias.' },
    { name:'CITAS',                  desc:'Programa. Gestiona. Nunca Pierdas Una Cita.' },
    { name:'CONSTRUCTOR WEB',        desc:'Construye. Lanza. Crece en Línea.' },
    { name:'MARKETING Y SEO',        desc:'Sé Encontrado. Obtén Clientes. Crece Más Rápido.' },
    { name:'ESTUDIO DE CONTENIDO',   desc:'Videos. Reels. Gráficos. Con IA.' },
    { name:'CRM Y VENTAS',           desc:'De Prospectos a Clientes Leales.' },
    { name:'ANALÍTICA',              desc:'Ideas. Reportes. Decisiones Más Inteligentes.' },
    { name:'AUTOMATIZACIÓN',         desc:'Flujos que Funcionan. Ahorra Tiempo. Escala Más.' },
  ],
  c:{ save:'Guardar', cancel:'Cancelar', edit:'Editar', delete:'Eliminar', add:'Agregar', new:'Nuevo', search:'Buscar…', loading:'Cargando…', back:'Atrás', name:'Nombre', email:'Correo', phone:'Teléfono', notes:'Notas', status:'Estado', date:'Fecha', time:'Hora', actions:'Acciones', noData:'Sin datos.', all:'Todos', confirm:'Confirmar', complete:'Completar', selectBiz:'Seleccionar negocio…' },
  call:{ newCall:'Nueva Llamada', dial:'📞 Marcar', end:'⏹ Terminar', answer:'📞 Contestar', decline:'📵 Rechazar', micOn:'🎙 Mic Activo', micOff:'🎙 Mic Inactivo', live:'LLAMADA EN VIVO', transcript:'Transcripción en Vivo', aiAssist:'Asistente IA', ringing:'Llamando…', connecting:'Conectando…', callerName:'Nombre del Llamante', reason:'Motivo de Llamada', today:'Llamadas Hoy', total:'Total Registrado', urgent:'Urgentes', ready:'⬤ Listo', noHistory:'Sin historial de llamadas.', duration:'Duración', triage:'Triaje', sentiment:'Sentimiento', analyzing:'⏳ Analizando…', analysisReady:'✅ Análisis listo', typeHint:'Escribe 30+ caracteres para activar IA' },
  biz:{ title:'Negocios / CRM', addNew:'+ Agregar Negocio', bizName:'Nombre del Negocio', industry:'Industria', revenue:'Ingresos ($)', employees:'Empleados', noData:'Sin negocios aún. ¡Agrega el primero!' },
  appt:{ title:'Citas', addNew:'+ Nueva Cita', business:'Negocio', service:'Servicio', custName:'Nombre del Cliente', custPhone:'Teléfono del Cliente', scheduled:'Programada', confirmed:'Confirmada', completed:'Completada', noData:'Sin citas aún.', quickAdd:'+ Agregar Negocio Rápido' },
  ai:{ title:'Analizador de Transcripciones IA', placeholder:'Pega la transcripción aquí…', analyze:'🧠 Analizar', analyzing:'⏳ Analizando…', summary:'Resumen', actionItems:'Acciones', noResult:'Pega una transcripción y haz clic en Analizar.' },
  dash:{ title:'Tablero', businesses:'Negocios', appointments:'Citas', calls:'Llamadas Hoy' },
})

// ── Urdu (RTL) ───────────────────────────────────────────────────────────────
const UR = m(EN, {
  rtl:true, langName:'اردو', flag:'🇵🇰',
  tagline:'کاروباری ترقی کے لیے آپ کی AI ورک فورس™',
  live:'براہ راست', reconnecting:'دوبارہ جڑ رہا ہے…',
  tabs:{ home:'🏠 ہوم', dashboard:'📊 ڈیش بورڈ', callCenter:'🎧 کال سینٹر', businesses:'🏢 سی آر ایم', appointments:'📅 ملاقاتیں', ai:'🤖 AI تجزیہ' },
  home:{ book:'ملاقات بک کریں', viewDash:'ڈیش بورڈ دیکھیں', heroTag:'— کاروباری ترقی کے لیے آپ کی AI ورک فورس™ —', comingSoon:'جلد آ رہا ہے', comingSoonSub:'یہ ماڈیول ابھی تیار ہو رہا ہے۔', back:'← واپس ہوم' },
  trust:['آل-ان-ون پلیٹ فارم','AI طاقت','انسانی منظوری','نتائج پر مبنی','محفوظ و قابل اعتماد'],
  features:[
    { name:'AI کال سینٹر',    desc:'ذہین گفتگو۔ بہتر کسٹمر تجربہ۔' },
    { name:'ملاقاتیں',         desc:'شیڈول کریں۔ منظم کریں۔ کبھی نہ بھولیں۔' },
    { name:'ویب سائٹ بلڈر',   desc:'بنائیں۔ لانچ کریں۔ آن لائن بڑھیں۔' },
    { name:'مارکیٹنگ و SEO',  desc:'ڈھونڈے جائیں۔ لیڈز پائیں۔' },
    { name:'کانٹینٹ اسٹوڈیو', desc:'ویڈیوز۔ ریلز۔ گرافکس۔ AI کے ساتھ۔' },
    { name:'سی آر ایم',        desc:'لیڈز سے وفادار گاہک۔' },
    { name:'تجزیات',           desc:'بصیرت۔ رپورٹس۔ بہتر فیصلے۔' },
    { name:'آٹومیشن',          desc:'کام کرنے والے ورک فلو۔ وقت بچائیں۔' },
  ],
  c:{ save:'محفوظ کریں', cancel:'منسوخ', edit:'ترمیم', delete:'حذف', add:'شامل کریں', new:'نیا', search:'تلاش کریں…', loading:'لوڈ ہو رہا ہے…', back:'واپس', name:'نام', email:'ای میل', phone:'فون', notes:'نوٹس', status:'حالت', date:'تاریخ', time:'وقت', actions:'اقدامات', noData:'کوئی ڈیٹا نہیں۔', all:'سب', confirm:'تصدیق کریں', complete:'مکمل کریں', selectBiz:'کاروبار منتخب کریں…' },
  call:{ newCall:'نئی کال', dial:'📞 ڈائل کریں', end:'⏹ کال ختم کریں', answer:'📞 اٹھائیں', decline:'📵 رد کریں', micOn:'🎙 مائک آن', micOff:'🎙 مائک آف', live:'براہ راست کال', transcript:'ٹرانسکرپٹ', aiAssist:'AI مددگار', ringing:'گھنٹی بج رہی ہے…', connecting:'جڑ رہا ہے…', callerName:'کال کرنے والے کا نام', reason:'کال کی وجہ', today:'آج کی کالیں', total:'کل درج', urgent:'فوری', ready:'⬤ تیار', noHistory:'کوئی کال تاریخ نہیں۔', duration:'مدت', triage:'درجہ بندی', sentiment:'جذبات', analyzing:'⏳ AI تجزیہ…', analysisReady:'✅ تجزیہ تیار', typeHint:'AI چالو کرنے کے لیے 30+ حروف لکھیں' },
  biz:{ title:'کاروبار / CRM', addNew:'+ کاروبار شامل کریں', bizName:'کاروبار کا نام', industry:'صنعت', revenue:'آمدنی ($)', employees:'ملازمین', noData:'ابھی کوئی کاروبار نہیں۔' },
  appt:{ title:'ملاقاتیں', addNew:'+ نئی ملاقات', business:'کاروبار', service:'سروس', custName:'گاہک کا نام', custPhone:'گاہک کا فون', scheduled:'طے شدہ', confirmed:'تصدیق شدہ', completed:'مکمل', noData:'ابھی کوئی ملاقات نہیں۔', quickAdd:'+ فوری کاروبار شامل کریں' },
  ai:{ title:'AI ٹرانسکرپٹ تجزیہ کار', placeholder:'یہاں ٹرانسکرپٹ پیسٹ کریں…', analyze:'🧠 تجزیہ کریں', analyzing:'⏳ تجزیہ ہو رہا ہے…', summary:'خلاصہ', actionItems:'اقدامات', noResult:'ٹرانسکرپٹ پیسٹ کریں اور تجزیہ پر کلک کریں۔' },
  dash:{ title:'ڈیش بورڈ', businesses:'کاروبار', appointments:'ملاقاتیں', calls:'آج کی کالیں' },
})

// ── Vietnamese ───────────────────────────────────────────────────────────────
const VI = m(EN, {
  rtl:false, langName:'Tiếng Việt', flag:'🇻🇳',
  tagline:'Lực Lượng AI Để Phát Triển Kinh Doanh™',
  live:'Trực tiếp', reconnecting:'Đang kết nối lại…',
  tabs:{ home:'🏠 Trang Chủ', dashboard:'📊 Bảng Điều Khiển', callCenter:'🎧 Trung Tâm Gọi', businesses:'🏢 CRM & Bán Hàng', appointments:'📅 Lịch Hẹn', ai:'🤖 Phân Tích AI' },
  home:{ book:'Đặt Lịch Hẹn', viewDash:'Xem Bảng Điều Khiển', heroTag:'— LỰC LƯỢNG AI CHO TĂNG TRƯỞNG KINH DOANH™ —', comingSoon:'Sắp Ra Mắt', comingSoonSub:'Module này đang được phát triển và sẽ có trong phiên bản tiếp theo.', back:'← Quay Lại Trang Chủ' },
  trust:['NỀN TẢNG TOÀN DIỆN','ĐƯỢC TRANG BỊ AI','ĐƯỢC CON NGƯỜI PHÊ DUYỆT','HƯỚNG ĐẾN KẾT QUẢ','AN TOÀN & ĐÁng TIN CẬY'],
  features:[
    { name:'TRUNG TÂM GỌI AI',  desc:'Trò Chuyện Thông Minh. Trải Nghiệm Khách Hàng Tốt Hơn.' },
    { name:'LỊCH HẸN',          desc:'Lên Lịch. Quản Lý. Không Bao Giờ Bỏ Lỡ.' },
    { name:'XÂY DỰNG WEBSITE',  desc:'Xây Dựng. Ra Mắt. Phát Triển Trực Tuyến.' },
    { name:'MARKETING & SEO',   desc:'Được Tìm Thấy. Có Khách Hàng. Phát Triển Nhanh Hơn.' },
    { name:'STUDIO NỘI DUNG',   desc:'Video. Reels. Đồ Họa. Được Hỗ Trợ Bởi AI.' },
    { name:'CRM & BÁN HÀNG',    desc:'Từ Tiềm Năng Đến Khách Hàng Trung Thành.' },
    { name:'PHÂN TÍCH',         desc:'Thông Tin. Báo Cáo. Quyết Định Thông Minh Hơn.' },
    { name:'TỰ ĐỘNG HÓA',       desc:'Quy Trình Làm Việc Hiệu Quả. Tiết Kiệm Thời Gian.' },
  ],
  c:{ save:'Lưu', cancel:'Hủy', edit:'Sửa', delete:'Xóa', add:'Thêm', new:'Mới', search:'Tìm kiếm…', loading:'Đang tải…', back:'Quay lại', name:'Tên', email:'Email', phone:'Điện thoại', notes:'Ghi chú', status:'Trạng thái', date:'Ngày', time:'Giờ', actions:'Hành động', noData:'Chưa có dữ liệu.', all:'Tất cả', confirm:'Xác nhận', complete:'Hoàn thành', selectBiz:'Chọn doanh nghiệp…' },
  call:{ newCall:'Cuộc Gọi Mới', dial:'📞 Gọi', end:'⏹ Kết Thúc', answer:'📞 Nghe', decline:'📵 Từ Chối', micOn:'🎙 Mic Bật', micOff:'🎙 Mic Tắt', live:'ĐANG GỌI', transcript:'Phiên Âm Trực Tiếp', aiAssist:'Hỗ Trợ AI', ringing:'Đang đổ chuông…', connecting:'Đang kết nối…', callerName:'Tên Người Gọi', reason:'Lý Do Gọi', today:'Cuộc Gọi Hôm Nay', total:'Tổng Đã Ghi', urgent:'Khẩn Cấp', ready:'⬤ Sẵn Sàng', noHistory:'Chưa có lịch sử cuộc gọi.', duration:'Thời Lượng', triage:'Mức Độ', sentiment:'Cảm Xúc', analyzing:'⏳ AI đang phân tích…', analysisReady:'✅ Phân tích xong', typeHint:'Gõ 30+ ký tự để kích hoạt AI' },
  biz:{ title:'Doanh Nghiệp / CRM', addNew:'+ Thêm Doanh Nghiệp', bizName:'Tên Doanh Nghiệp', industry:'Ngành', revenue:'Doanh Thu ($)', employees:'Nhân Viên', noData:'Chưa có doanh nghiệp nào. Thêm ngay!' },
  appt:{ title:'Lịch Hẹn', addNew:'+ Lịch Hẹn Mới', business:'Doanh Nghiệp', service:'Dịch Vụ', custName:'Tên Khách Hàng', custPhone:'Điện Thoại Khách Hàng', scheduled:'Đã Lên Lịch', confirmed:'Đã Xác Nhận', completed:'Hoàn Thành', noData:'Chưa có lịch hẹn.', quickAdd:'+ Thêm Nhanh Doanh Nghiệp' },
  ai:{ title:'Phân Tích Phiên Âm AI', placeholder:'Dán phiên âm cuộc gọi vào đây…', analyze:'🧠 Phân Tích', analyzing:'⏳ Đang phân tích…', summary:'Tóm Tắt', actionItems:'Hành Động Cần Làm', noResult:'Dán phiên âm và nhấn Phân Tích.' },
  dash:{ title:'Bảng Điều Khiển', businesses:'Doanh Nghiệp', appointments:'Lịch Hẹn', calls:'Cuộc Gọi Hôm Nay' },
})

// ── French ───────────────────────────────────────────────────────────────────
const FR = m(EN, {
  rtl:false, langName:'Français', flag:'🇫🇷',
  tagline:"Votre Main-d'Œuvre IA pour la Croissance™",
  live:'En direct', reconnecting:'Reconnexion…',
  tabs:{ home:'🏠 Accueil', dashboard:'📊 Tableau de Bord', callCenter:'🎧 Centre d\'Appels', businesses:'🏢 CRM & Ventes', appointments:'📅 Rendez-vous', ai:'🤖 Analyseur IA' },
  home:{ book:'Prendre Rendez-vous', viewDash:'Voir le Tableau de Bord', heroTag:'— VOTRE MAIN-D\'ŒUVRE IA POUR LA CROISSANCE™ —', comingSoon:'Bientôt Disponible', comingSoonSub:"Ce module est en cours de développement et sera disponible dans la prochaine version.", back:'← Retour à l\'Accueil' },
  trust:['PLATEFORME TOUT-EN-UN','PROPULSÉ PAR IA','APPROUVÉ PAR L\'HUMAIN','AXÉS SUR LES RÉSULTATS','SÉCURISÉ ET FIABLE'],
  c:{ save:'Enregistrer', cancel:'Annuler', edit:'Modifier', delete:'Supprimer', add:'Ajouter', new:'Nouveau', search:'Rechercher…', loading:'Chargement…', back:'Retour', name:'Nom', email:'Email', phone:'Téléphone', notes:'Notes', status:'Statut', date:'Date', time:'Heure', actions:'Actions', noData:'Aucune donnée.', all:'Tous', confirm:'Confirmer', complete:'Terminer', selectBiz:'Sélectionner une entreprise…' },
  call:{ newCall:'Nouvel Appel', dial:'📞 Composer', end:'⏹ Fin d\'Appel', answer:'📞 Répondre', decline:'📵 Refuser', micOn:'🎙 Micro Activé', micOff:'🎙 Micro Désactivé', live:'APPEL EN DIRECT', transcript:'Transcription en Direct', aiAssist:'Assistance IA', ringing:'Sonnerie…', connecting:'Connexion…', callerName:'Nom de l\'Appelant', reason:'Motif de l\'Appel', today:'Appels Aujourd\'hui', total:'Total Enregistré', urgent:'Urgents', ready:'⬤ Prêt', noHistory:'Aucun historique d\'appels.', duration:'Durée', triage:'Triage', sentiment:'Sentiment', analyzing:'⏳ Analyse IA…', analysisReady:'✅ Analyse prête', typeHint:'Tapez 30+ caractères pour activer l\'IA' },
  biz:{ title:'Entreprises / CRM', addNew:'+ Ajouter Entreprise', bizName:'Nom de l\'Entreprise', industry:'Secteur', revenue:'Revenus ($)', employees:'Employés', noData:'Aucune entreprise. Ajoutez la première!' },
  appt:{ title:'Rendez-vous', addNew:'+ Nouveau Rendez-vous', business:'Entreprise', service:'Service', custName:'Nom du Client', custPhone:'Téléphone Client', scheduled:'Planifié', confirmed:'Confirmé', completed:'Terminé', noData:'Aucun rendez-vous.', quickAdd:'+ Ajouter Entreprise Rapidement' },
  ai:{ title:'Analyseur de Transcription IA', placeholder:'Collez la transcription ici…', analyze:'🧠 Analyser', analyzing:'⏳ Analyse en cours…', summary:'Résumé', actionItems:'Actions à Faire', noResult:'Collez une transcription et cliquez sur Analyser.' },
  dash:{ title:'Tableau de Bord', businesses:'Entreprises', appointments:'Rendez-vous', calls:"Appels Aujourd'hui" },
})

// ── Chinese Simplified ────────────────────────────────────────────────────────
const ZH = m(EN, {
  rtl:false, langName:'中文', flag:'🇨🇳',
  tagline:'您的AI劳动力，助力企业增长™',
  live:'实时', reconnecting:'重新连接中…',
  tabs:{ home:'🏠 首页', dashboard:'📊 仪表板', callCenter:'🎧 呼叫中心', businesses:'🏢 CRM与销售', appointments:'📅 预约', ai:'🤖 AI分析' },
  home:{ book:'预约', viewDash:'查看仪表板', heroTag:'— 您的AI劳动力，助力企业增长™ —', comingSoon:'即将推出', comingSoonSub:'该模块正在开发中，将在下一版本中提供。', back:'← 返回首页' },
  trust:['一体化平台','AI驱动','人工审核','以结果为导向','安全可靠'],
  c:{ save:'保存', cancel:'取消', edit:'编辑', delete:'删除', add:'添加', new:'新建', search:'搜索…', loading:'加载中…', back:'返回', name:'名称', email:'邮箱', phone:'电话', notes:'备注', status:'状态', date:'日期', time:'时间', actions:'操作', noData:'暂无数据。', all:'全部', confirm:'确认', complete:'完成', selectBiz:'选择企业…' },
  call:{ newCall:'新呼叫', dial:'📞 拨打', end:'⏹ 结束通话', answer:'📞 接听', decline:'📵 拒绝', micOn:'🎙 麦克风开', micOff:'🎙 麦克风关', live:'实时通话', transcript:'实时转录', aiAssist:'AI助手', ringing:'响铃中…', connecting:'连接中…', callerName:'来电人姓名', reason:'来电原因', today:'今日通话', total:'总记录', urgent:'紧急', ready:'⬤ 就绪', noHistory:'暂无通话记录。', duration:'时长', triage:'分诊', sentiment:'情感', analyzing:'⏳ AI分析中…', analysisReady:'✅ 分析完成', typeHint:'输入30+字符以触发AI' },
  biz:{ title:'企业/CRM', addNew:'+ 添加企业', bizName:'企业名称', industry:'行业', revenue:'收入 ($)', employees:'员工数', noData:'暂无企业。请添加第一个！' },
  appt:{ title:'预约', addNew:'+ 新预约', business:'企业', service:'服务', custName:'客户姓名', custPhone:'客户电话', scheduled:'已安排', confirmed:'已确认', completed:'已完成', noData:'暂无预约。', quickAdd:'+ 快速添加企业' },
  ai:{ title:'AI转录分析器', placeholder:'在此粘贴通话转录…', analyze:'🧠 分析', analyzing:'⏳ 分析中…', summary:'摘要', actionItems:'行动项', noResult:'粘贴转录内容，然后点击分析。' },
  dash:{ title:'仪表板', businesses:'企业', appointments:'预约', calls:'今日通话' },
})

// ── Tagalog / Filipino ────────────────────────────────────────────────────────
const TL = m(EN, {
  rtl:false, langName:'Filipino', flag:'🇵🇭',
  tagline:'Ang Inyong AI Workforce para sa Paglago ng Negosyo™',
  live:'Live', reconnecting:'Muling nagkokonekta…',
  tabs:{ home:'🏠 Tahanan', dashboard:'📊 Dashboard', callCenter:'🎧 Call Center', businesses:'🏢 CRM at Benta', appointments:'📅 Appointment', ai:'🤖 AI Analyzer' },
  home:{ book:'Mag-book ng Appointment', viewDash:'Tingnan ang Dashboard', heroTag:'— ANG INYONG AI WORKFORCE PARA SA PAGLAGO™ —', comingSoon:'Malapit Nang Lumabas', comingSoonSub:'Ang module na ito ay kasalukuyang pinagtatrabahuhan at maaari sa susunod na release.', back:'← Bumalik sa Tahanan' },
  trust:['ALL-IN-ONE PLATFORM','PINAPAGANA NG AI','INAAPRUBAHAN NG TAO','NAKATUON SA RESULTA','LIGTAS AT MAAASAHAN'],
  c:{ save:'I-save', cancel:'Kanselahin', edit:'I-edit', delete:'Burahin', add:'Idagdag', new:'Bago', search:'Maghanap…', loading:'Naglo-load…', back:'Bumalik', name:'Pangalan', email:'Email', phone:'Telepono', notes:'Tala', status:'Katayuan', date:'Petsa', time:'Oras', actions:'Aksyon', noData:'Wala pang data.', all:'Lahat', confirm:'Kumpirmahin', complete:'Kumpletuhin', selectBiz:'Pumili ng negosyo…' },
  call:{ newCall:'Bagong Tawag', dial:'📞 Tumawag', end:'⏹ Tapusin ang Tawag', answer:'📞 Sagutin', decline:'📵 Tanggihan', micOn:'🎙 Mic Bukas', micOff:'🎙 Mic Sarado', live:'LIVE NA TAWAG', transcript:'Live na Transkripsiyon', aiAssist:'AI Tulong', ringing:'Tumatunog…', connecting:'Nagkokonekta…', callerName:'Pangalan ng Tumatawag', reason:'Dahilan ng Tawag', today:'Mga Tawag Ngayon', total:'Kabuuang Naitala', urgent:'Urgent', ready:'⬤ Handa', noHistory:'Wala pang kasaysayan ng tawag.', duration:'Tagal', triage:'Triage', sentiment:'Damdamin', analyzing:'⏳ AI nag-aanalisa…', analysisReady:'✅ Handa na ang pagsusuri', typeHint:'Mag-type ng 30+ karakter para sa AI' },
  biz:{ title:'Mga Negosyo / CRM', addNew:'+ Magdagdag ng Negosyo', bizName:'Pangalan ng Negosyo', industry:'Industriya', revenue:'Kita ($)', employees:'Mga Empleyado', noData:'Wala pang negosyo. Magdagdag ng una!' },
  appt:{ title:'Mga Appointment', addNew:'+ Bagong Appointment', business:'Negosyo', service:'Serbisyo', custName:'Pangalan ng Customer', custPhone:'Telepono ng Customer', scheduled:'Nakatakda', confirmed:'Nakumpirma', completed:'Nakumpleto', noData:'Wala pang appointment.', quickAdd:'+ Mabilis na Idagdag ang Negosyo' },
  ai:{ title:'AI Transcript Analyzer', placeholder:'I-paste ang transcript dito…', analyze:'🧠 Suriin', analyzing:'⏳ Sinusuri…', summary:'Buod', actionItems:'Mga Aksyon', noResult:'I-paste ang transcript at i-click ang Suriin.' },
  dash:{ title:'Dashboard', businesses:'Mga Negosyo', appointments:'Mga Appointment', calls:'Mga Tawag Ngayon' },
})

// ── Korean ────────────────────────────────────────────────────────────────────
const KO = m(EN, {
  rtl:false, langName:'한국어', flag:'🇰🇷',
  tagline:'비즈니스 성장을 위한 AI 인력™',
  live:'실시간', reconnecting:'재연결 중…',
  tabs:{ home:'🏠 홈', dashboard:'📊 대시보드', callCenter:'🎧 콜 센터', businesses:'🏢 CRM & 영업', appointments:'📅 예약', ai:'🤖 AI 분석기' },
  home:{ book:'예약하기', viewDash:'대시보드 보기', heroTag:'— 비즈니스 성장을 위한 AI 인력™ —', comingSoon:'출시 예정', comingSoonSub:'이 모듈은 개발 중이며 다음 릴리스에 포함될 예정입니다.', back:'← 홈으로 돌아가기' },
  trust:['올인원 플랫폼','AI 기반','인간 승인','결과 중심','안전 및 신뢰'],
  c:{ save:'저장', cancel:'취소', edit:'수정', delete:'삭제', add:'추가', new:'새로', search:'검색…', loading:'로딩 중…', back:'뒤로', name:'이름', email:'이메일', phone:'전화', notes:'메모', status:'상태', date:'날짜', time:'시간', actions:'작업', noData:'데이터 없음.', all:'전체', confirm:'확인', complete:'완료', selectBiz:'비즈니스 선택…' },
  call:{ newCall:'새 통화', dial:'📞 전화걸기', end:'⏹ 통화 종료', answer:'📞 수신', decline:'📵 거절', micOn:'🎙 마이크 켜짐', micOff:'🎙 마이크 꺼짐', live:'실시간 통화', transcript:'실시간 녹취', aiAssist:'AI 도움', ringing:'연결 중…', connecting:'접속 중…', callerName:'발신자 이름', reason:'통화 사유', today:'오늘 통화', total:'총 기록', urgent:'긴급', ready:'⬤ 준비', noHistory:'통화 기록이 없습니다.', duration:'통화 시간', triage:'분류', sentiment:'감정', analyzing:'⏳ AI 분석 중…', analysisReady:'✅ 분석 완료', typeHint:'AI를 활성화하려면 30자 이상 입력하세요' },
  biz:{ title:'비즈니스 / CRM', addNew:'+ 비즈니스 추가', bizName:'비즈니스 이름', industry:'업종', revenue:'매출 ($)', employees:'직원 수', noData:'비즈니스가 없습니다. 첫 번째를 추가하세요!' },
  appt:{ title:'예약', addNew:'+ 새 예약', business:'비즈니스', service:'서비스', custName:'고객 이름', custPhone:'고객 전화', scheduled:'예약됨', confirmed:'확인됨', completed:'완료됨', noData:'예약이 없습니다.', quickAdd:'+ 비즈니스 빠른 추가' },
  ai:{ title:'AI 녹취 분석기', placeholder:'통화 녹취를 여기에 붙여넣으세요…', analyze:'🧠 분석', analyzing:'⏳ 분석 중…', summary:'요약', actionItems:'실행 항목', noResult:'녹취를 붙여넣고 분석을 클릭하세요.' },
  dash:{ title:'대시보드', businesses:'비즈니스', appointments:'예약', calls:'오늘 통화' },
})

// ── Arabic (RTL) ──────────────────────────────────────────────────────────────
const AR = m(EN, {
  rtl:true, langName:'العربية', flag:'🇸🇦',
  tagline:'قوتك العاملة بالذكاء الاصطناعي لنمو أعمالك™',
  live:'مباشر', reconnecting:'إعادة الاتصال…',
  tabs:{ home:'🏠 الرئيسية', dashboard:'📊 لوحة التحكم', callCenter:'🎧 مركز الاتصال', businesses:'🏢 CRM والمبيعات', appointments:'📅 المواعيد', ai:'🤖 محلل الذكاء' },
  home:{ book:'حجز موعد', viewDash:'عرض لوحة التحكم', heroTag:'— قوتك العاملة بالذكاء الاصطناعي لنمو أعمالك™ —', comingSoon:'قريباً', comingSoonSub:'هذه الوحدة قيد التطوير وستكون متاحة في الإصدار القادم.', back:'← العودة للرئيسية' },
  trust:['منصة متكاملة','مدعوم بالذكاء الاصطناعي','معتمد بشرياً','موجه نحو النتائج','آمن وموثوق'],
  c:{ save:'حفظ', cancel:'إلغاء', edit:'تعديل', delete:'حذف', add:'إضافة', new:'جديد', search:'بحث…', loading:'جارٍ التحميل…', back:'رجوع', name:'الاسم', email:'البريد', phone:'الهاتف', notes:'ملاحظات', status:'الحالة', date:'التاريخ', time:'الوقت', actions:'إجراءات', noData:'لا توجد بيانات.', all:'الكل', confirm:'تأكيد', complete:'إكمال', selectBiz:'اختر شركة…' },
  call:{ newCall:'مكالمة جديدة', dial:'📞 اتصال', end:'⏹ إنهاء المكالمة', answer:'📞 إجابة', decline:'📵 رفض', micOn:'🎙 ميكروفون مفعّل', micOff:'🎙 ميكروفون معطّل', live:'مكالمة مباشرة', transcript:'النص الحي', aiAssist:'مساعد الذكاء', ringing:'يرن…', connecting:'يتصل…', callerName:'اسم المتصل', reason:'سبب الاتصال', today:'مكالمات اليوم', total:'الإجمالي المسجل', urgent:'عاجل', ready:'⬤ جاهز', noHistory:'لا يوجد سجل مكالمات.', duration:'المدة', triage:'الفرز', sentiment:'المشاعر', analyzing:'⏳ تحليل الذكاء…', analysisReady:'✅ التحليل جاهز', typeHint:'اكتب 30+ حرفاً لتفعيل الذكاء الاصطناعي' },
  biz:{ title:'الشركات / CRM', addNew:'+ إضافة شركة', bizName:'اسم الشركة', industry:'الصناعة', revenue:'الإيرادات ($)', employees:'الموظفون', noData:'لا توجد شركات بعد. أضف الأولى!' },
  appt:{ title:'المواعيد', addNew:'+ موعد جديد', business:'الشركة', service:'الخدمة', custName:'اسم العميل', custPhone:'هاتف العميل', scheduled:'مجدول', confirmed:'مؤكد', completed:'مكتمل', noData:'لا توجد مواعيد.', quickAdd:'+ إضافة شركة سريعة' },
  ai:{ title:'محلل النصوص بالذكاء الاصطناعي', placeholder:'الصق نص المكالمة هنا…', analyze:'🧠 تحليل', analyzing:'⏳ جارٍ التحليل…', summary:'ملخص', actionItems:'الإجراءات', noResult:'الصق نصاً وانقر تحليل.' },
  dash:{ title:'لوحة التحكم', businesses:'الشركات', appointments:'المواعيد', calls:'مكالمات اليوم' },
})

// ── Hindi ─────────────────────────────────────────────────────────────────────
const HI = m(EN, {
  rtl:false, langName:'हिन्दी', flag:'🇮🇳',
  tagline:'व्यापार विकास के लिए आपकी AI कार्यबल™',
  live:'लाइव', reconnecting:'पुनः जुड़ रहा है…',
  tabs:{ home:'🏠 होम', dashboard:'📊 डैशबोर्ड', callCenter:'🎧 कॉल सेंटर', businesses:'🏢 CRM और बिक्री', appointments:'📅 अपॉइंटमेंट', ai:'🤖 AI विश्लेषक' },
  home:{ book:'अपॉइंटमेंट बुक करें', viewDash:'डैशबोर्ड देखें', heroTag:'— व्यापार विकास के लिए आपकी AI कार्यबल™ —', comingSoon:'जल्द आ रहा है', comingSoonSub:'यह मॉड्यूल विकास में है और अगले रिलीज़ में उपलब्ध होगा।', back:'← होम पर वापस जाएं' },
  trust:['ऑल-इन-वन प्लेटफ़ॉर्म','AI संचालित','मानव अनुमोदित','परिणाम केंद्रित','सुरक्षित और विश्वसनीय'],
  c:{ save:'सहेजें', cancel:'रद्द करें', edit:'संपादित करें', delete:'हटाएं', add:'जोड़ें', new:'नया', search:'खोजें…', loading:'लोड हो रहा है…', back:'वापस', name:'नाम', email:'ईमेल', phone:'फ़ोन', notes:'नोट्स', status:'स्थिति', date:'तारीख', time:'समय', actions:'क्रियाएं', noData:'कोई डेटा नहीं।', all:'सभी', confirm:'पुष्टि करें', complete:'पूरा करें', selectBiz:'व्यवसाय चुनें…' },
  call:{ newCall:'नई कॉल', dial:'📞 डायल करें', end:'⏹ कॉल समाप्त करें', answer:'📞 उठाएं', decline:'📵 अस्वीकार करें', micOn:'🎙 माइक चालू', micOff:'🎙 माइक बंद', live:'लाइव कॉल', transcript:'लाइव ट्रांसक्रिप्ट', aiAssist:'AI सहायता', ringing:'रिंग हो रही है…', connecting:'जुड़ रहा है…', callerName:'कॉलर का नाम', reason:'कॉल का कारण', today:'आज की कॉल', total:'कुल दर्ज', urgent:'अत्यावश्यक', ready:'⬤ तैयार', noHistory:'कोई कॉल इतिहास नहीं।', duration:'अवधि', triage:'ट्रायज', sentiment:'भावना', analyzing:'⏳ AI विश्लेषण…', analysisReady:'✅ विश्लेषण तैयार', typeHint:'AI सक्रिय करने के लिए 30+ अक्षर टाइप करें' },
  biz:{ title:'व्यवसाय / CRM', addNew:'+ व्यवसाय जोड़ें', bizName:'व्यवसाय का नाम', industry:'उद्योग', revenue:'राजस्व ($)', employees:'कर्मचारी', noData:'अभी कोई व्यवसाय नहीं। पहला जोड़ें!' },
  appt:{ title:'अपॉइंटमेंट', addNew:'+ नई अपॉइंटमेंट', business:'व्यवसाय', service:'सेवा', custName:'ग्राहक का नाम', custPhone:'ग्राहक का फ़ोन', scheduled:'निर्धारित', confirmed:'पुष्टि हुई', completed:'पूर्ण', noData:'अभी कोई अपॉइंटमेंट नहीं।', quickAdd:'+ त्वरित व्यवसाय जोड़ें' },
  ai:{ title:'AI ट्रांसक्रिप्ट विश्लेषक', placeholder:'यहाँ ट्रांसक्रिप्ट पेस्ट करें…', analyze:'🧠 विश्लेषण करें', analyzing:'⏳ विश्लेषण हो रहा है…', summary:'सारांश', actionItems:'कार्य आइटम', noResult:'ट्रांसक्रिप्ट पेस्ट करें और विश्लेषण पर क्लिक करें।' },
  dash:{ title:'डैशबोर्ड', businesses:'व्यवसाय', appointments:'अपॉइंटमेंट', calls:'आज की कॉल' },
})

// ── Portuguese ────────────────────────────────────────────────────────────────
const PT = m(EN, {
  rtl:false, langName:'Português', flag:'🇧🇷',
  tagline:'Sua Força de Trabalho IA para o Crescimento™',
  live:'Ao Vivo', reconnecting:'Reconectando…',
  tabs:{ home:'🏠 Início', dashboard:'📊 Painel', callCenter:'🎧 Central de Chamadas', businesses:'🏢 CRM e Vendas', appointments:'📅 Agendamentos', ai:'🤖 Analisador IA' },
  home:{ book:'Agendar Consulta', viewDash:'Ver Painel', heroTag:'— SUA FORÇA DE TRABALHO IA PARA CRESCER™ —', comingSoon:'Em Breve', comingSoonSub:'Este módulo está em desenvolvimento e estará disponível na próxima versão.', back:'← Voltar ao Início' },
  trust:['PLATAFORMA TUDO-EM-UM','MOVIDO POR IA','APROVADO POR HUMANOS','ORIENTADO A RESULTADOS','SEGURO E CONFIÁVEL'],
  c:{ save:'Salvar', cancel:'Cancelar', edit:'Editar', delete:'Excluir', add:'Adicionar', new:'Novo', search:'Pesquisar…', loading:'Carregando…', back:'Voltar', name:'Nome', email:'Email', phone:'Telefone', notes:'Notas', status:'Status', date:'Data', time:'Hora', actions:'Ações', noData:'Sem dados.', all:'Todos', confirm:'Confirmar', complete:'Concluir', selectBiz:'Selecionar empresa…' },
  call:{ newCall:'Nova Chamada', dial:'📞 Ligar', end:'⏹ Encerrar', answer:'📞 Atender', decline:'📵 Recusar', micOn:'🎙 Mic Ativo', micOff:'🎙 Mic Inativo', live:'CHAMADA AO VIVO', transcript:'Transcrição ao Vivo', aiAssist:'Assistente IA', ringing:'Chamando…', connecting:'Conectando…', callerName:'Nome do Chamador', reason:'Motivo da Chamada', today:'Chamadas Hoje', total:'Total Registrado', urgent:'Urgente', ready:'⬤ Pronto', noHistory:'Sem histórico de chamadas.', duration:'Duração', triage:'Triagem', sentiment:'Sentimento', analyzing:'⏳ Analisando com IA…', analysisReady:'✅ Análise pronta', typeHint:'Digite 30+ caracteres para ativar IA' },
  biz:{ title:'Empresas / CRM', addNew:'+ Adicionar Empresa', bizName:'Nome da Empresa', industry:'Setor', revenue:'Receita ($)', employees:'Funcionários', noData:'Nenhuma empresa. Adicione a primeira!' },
  appt:{ title:'Agendamentos', addNew:'+ Novo Agendamento', business:'Empresa', service:'Serviço', custName:'Nome do Cliente', custPhone:'Telefone do Cliente', scheduled:'Agendado', confirmed:'Confirmado', completed:'Concluído', noData:'Sem agendamentos.', quickAdd:'+ Adicionar Empresa Rápido' },
  ai:{ title:'Analisador de Transcrição IA', placeholder:'Cole a transcrição aqui…', analyze:'🧠 Analisar', analyzing:'⏳ Analisando…', summary:'Resumo', actionItems:'Ações', noResult:'Cole uma transcrição e clique em Analisar.' },
  dash:{ title:'Painel', businesses:'Empresas', appointments:'Agendamentos', calls:'Chamadas Hoje' },
})

// ── Russian ───────────────────────────────────────────────────────────────────
const RU = m(EN, {
  rtl:false, langName:'Русский', flag:'🇷🇺',
  tagline:'Ваша AI-Рабочая Сила для Роста Бизнеса™',
  live:'В эфире', reconnecting:'Переподключение…',
  tabs:{ home:'🏠 Главная', dashboard:'📊 Дашборд', callCenter:'🎧 Колл-центр', businesses:'🏢 CRM и Продажи', appointments:'📅 Записи', ai:'🤖 AI Анализатор' },
  home:{ book:'Записаться', viewDash:'Открыть Дашборд', heroTag:'— ВАША AI-РАБОЧАЯ СИЛА ДЛЯ РОСТА БИЗНЕСА™ —', comingSoon:'Скоро', comingSoonSub:'Этот модуль находится в разработке и будет доступен в следующем релизе.', back:'← На главную' },
  trust:['ВСЁВКЛЮЧЁННАЯ ПЛАТФОРМА','НА ОСНОВЕ ИИ','ОДОБРЕНО ЛЮДЬМИ','ОРИЕНТИРОВАНО НА РЕЗУЛЬТАТ','БЕЗОПАСНО И НАДЁЖНО'],
  c:{ save:'Сохранить', cancel:'Отмена', edit:'Редактировать', delete:'Удалить', add:'Добавить', new:'Новый', search:'Поиск…', loading:'Загрузка…', back:'Назад', name:'Имя', email:'Email', phone:'Телефон', notes:'Заметки', status:'Статус', date:'Дата', time:'Время', actions:'Действия', noData:'Нет данных.', all:'Все', confirm:'Подтвердить', complete:'Завершить', selectBiz:'Выберите бизнес…' },
  call:{ newCall:'Новый звонок', dial:'📞 Позвонить', end:'⏹ Завершить', answer:'📞 Ответить', decline:'📵 Отклонить', micOn:'🎙 Мик включён', micOff:'🎙 Мик выключен', live:'ЖИВОЙ ЗВОНОК', transcript:'Транскрипт', aiAssist:'Помощь ИИ', ringing:'Звонок…', connecting:'Подключение…', callerName:'Имя звонящего', reason:'Причина звонка', today:'Звонки сегодня', total:'Всего записей', urgent:'Срочный', ready:'⬤ Готов', noHistory:'Нет истории звонков.', duration:'Длительность', triage:'Триаж', sentiment:'Тональность', analyzing:'⏳ AI анализирует…', analysisReady:'✅ Анализ готов', typeHint:'Введите 30+ символов для AI' },
  biz:{ title:'Бизнес / CRM', addNew:'+ Добавить бизнес', bizName:'Название бизнеса', industry:'Отрасль', revenue:'Доход ($)', employees:'Сотрудники', noData:'Нет бизнесов. Добавьте первый!' },
  appt:{ title:'Записи', addNew:'+ Новая запись', business:'Бизнес', service:'Услуга', custName:'Имя клиента', custPhone:'Телефон клиента', scheduled:'Запланировано', confirmed:'Подтверждено', completed:'Завершено', noData:'Нет записей.', quickAdd:'+ Быстро добавить бизнес' },
  ai:{ title:'AI Анализатор транскриптов', placeholder:'Вставьте транскрипт сюда…', analyze:'🧠 Анализировать', analyzing:'⏳ Анализ…', summary:'Сводка', actionItems:'Задачи', noResult:'Вставьте транскрипт и нажмите Анализировать.' },
  dash:{ title:'Дашборд', businesses:'Бизнесы', appointments:'Записи', calls:'Звонки сегодня' },
})

// ── Haitian Creole ────────────────────────────────────────────────────────────
const HT = m(EN, {
  rtl:false, langName:'Kreyòl Ayisyen', flag:'🇭🇹',
  tagline:'Fòs Travay AI Ou pou Kwasans Biznis™',
  live:'Dirèk', reconnecting:'Rekonekte…',
  tabs:{ home:'🏠 Akèy', dashboard:'📊 Tablo Bò', callCenter:'🎧 Sant Apèl', businesses:'🏢 CRM ak Vant', appointments:'📅 Randevou', ai:'🤖 Analizè AI' },
  home:{ book:'Pran Randevou', viewDash:'Wè Tablo Bò', heroTag:'— FÒS TRAVAY AI OU POU KWASANS BIZNIS™ —', comingSoon:'Bientôt Disponib', comingSoonSub:'Modil sa a ap devlope epi li pral disponib nan pwochen vèsyon an.', back:'← Retounen Akèy' },
  trust:['PLATFÒM TOU-AN-YON','ALIMANTE PA AI','APWOUVE PA IMEN','ORANTE VÈ REZILTA','SEKIRIZE EPI FYAB'],
  c:{ save:'Anrejistre', cancel:'Anile', edit:'Modifye', delete:'Efase', add:'Ajoute', new:'Nouvo', search:'Chèche…', loading:'Ap chaje…', back:'Retounen', name:'Non', email:'Imèl', phone:'Telefòn', notes:'Nòt', status:'Estati', date:'Dat', time:'Lè', actions:'Aksyon', noData:'Pa gen done.', all:'Tout', confirm:'Konfime', complete:'Konplete', selectBiz:'Chwazi biznis…' },
  call:{ newCall:'Nouvo Apèl', dial:'📞 Rele', end:'⏹ Fini Apèl', answer:'📞 Reponn', decline:'📵 Refize', micOn:'🎙 Mik Aktif', micOff:'🎙 Mik Dezaktive', live:'APÈL DIRÈK', transcript:'Transkripsyon', aiAssist:'Èd AI', ringing:'Ap sonnen…', connecting:'Ap konekte…', callerName:'Non Moun ki Rele', reason:'Rezon Apèl', today:'Apèl Jodi', total:'Total Anrejistre', urgent:'Ijan', ready:'⬤ Prè', noHistory:'Pa gen istwa apèl.', duration:'Dire', triage:'Triaj', sentiment:'Santiman', analyzing:'⏳ AI ap analize…', analysisReady:'✅ Analiz prè', typeHint:'Ekri 30+ karaktè pou aktive AI' },
  biz:{ title:'Biznis / CRM', addNew:'+ Ajoute Biznis', bizName:'Non Biznis', industry:'Endistri', revenue:'Revni ($)', employees:'Anplwaye', noData:'Pa gen biznis. Ajoute premye a!' },
  appt:{ title:'Randevou', addNew:'+ Nouvo Randevou', business:'Biznis', service:'Sèvis', custName:'Non Kliyan', custPhone:'Telefòn Kliyan', scheduled:'Planifye', confirmed:'Konfime', completed:'Konplete', noData:'Pa gen randevou.', quickAdd:'+ Vit Ajoute Biznis' },
  ai:{ title:'Analizè Transkripsyon AI', placeholder:'Kole transkripsyon la isit…', analyze:'🧠 Analize', analyzing:'⏳ Ap analize…', summary:'Rezime', actionItems:'Aksyon', noResult:'Kole transkripsyon epi klike Analize.' },
  dash:{ title:'Tablo Bò', businesses:'Biznis', appointments:'Randevou', calls:'Apèl Jodi' },
})

// ── Polish ────────────────────────────────────────────────────────────────────
const PL = m(EN, {
  rtl:false, langName:'Polski', flag:'🇵🇱',
  tagline:'Twoja Siła Robocza AI dla Wzrostu Biznesu™',
  live:'Na żywo', reconnecting:'Ponowne łączenie…',
  tabs:{ home:'🏠 Strona główna', dashboard:'📊 Panel', callCenter:'🎧 Centrum obsługi', businesses:'🏢 CRM i Sprzedaż', appointments:'📅 Wizyty', ai:'🤖 Analizator AI' },
  home:{ book:'Umów wizytę', viewDash:'Zobacz panel', heroTag:'— TWOJA SIŁA ROBOCZA AI DLA WZROSTU™ —', comingSoon:'Już Wkrótce', comingSoonSub:'Ten moduł jest w trakcie tworzenia i będzie dostępny w kolejnej wersji.', back:'← Wróć na stronę główną' },
  trust:['PLATFORMA WSZYSTKO-W-JEDNYM','NAPĘDZANA PRZEZ AI','ZATWIERDZONA PRZEZ CZŁOWIEKA','ZORIENTOWANA NA WYNIKI','BEZPIECZNA I NIEZAWODNA'],
  c:{ save:'Zapisz', cancel:'Anuluj', edit:'Edytuj', delete:'Usuń', add:'Dodaj', new:'Nowy', search:'Szukaj…', loading:'Ładowanie…', back:'Wstecz', name:'Nazwa', email:'Email', phone:'Telefon', notes:'Notatki', status:'Status', date:'Data', time:'Czas', actions:'Akcje', noData:'Brak danych.', all:'Wszystko', confirm:'Potwierdź', complete:'Zakończ', selectBiz:'Wybierz firmę…' },
  call:{ newCall:'Nowe połączenie', dial:'📞 Zadzwoń', end:'⏹ Zakończ', answer:'📞 Odbierz', decline:'📵 Odrzuć', micOn:'🎙 Mikrofon włączony', micOff:'🎙 Mikrofon wyłączony', live:'ROZMOWA NA ŻYWO', transcript:'Transkrypcja na żywo', aiAssist:'Pomoc AI', ringing:'Dzwoni…', connecting:'Łączenie…', callerName:'Imię dzwoniącego', reason:'Powód połączenia', today:'Połączenia dziś', total:'Łącznie zapisanych', urgent:'Pilne', ready:'⬤ Gotowy', noHistory:'Brak historii połączeń.', duration:'Czas trwania', triage:'Triage', sentiment:'Nastrój', analyzing:'⏳ AI analizuje…', analysisReady:'✅ Analiza gotowa', typeHint:'Wpisz 30+ znaków, aby aktywować AI' },
  biz:{ title:'Firmy / CRM', addNew:'+ Dodaj firmę', bizName:'Nazwa firmy', industry:'Branża', revenue:'Przychód ($)', employees:'Pracownicy', noData:'Brak firm. Dodaj pierwszą!' },
  appt:{ title:'Wizyty', addNew:'+ Nowa wizyta', business:'Firma', service:'Usługa', custName:'Imię klienta', custPhone:'Telefon klienta', scheduled:'Zaplanowane', confirmed:'Potwierdzone', completed:'Zakończone', noData:'Brak wizyt.', quickAdd:'+ Szybko dodaj firmę' },
  ai:{ title:'Analizator transkrypcji AI', placeholder:'Wklej transkrypcję tutaj…', analyze:'🧠 Analizuj', analyzing:'⏳ Analizowanie…', summary:'Podsumowanie', actionItems:'Działania', noResult:'Wklej transkrypcję i kliknij Analizuj.' },
  dash:{ title:'Panel', businesses:'Firmy', appointments:'Wizyty', calls:'Połączenia dziś' },
})

// ── Punjabi ───────────────────────────────────────────────────────────────────
const PA = m(EN, {
  rtl:false, langName:'ਪੰਜਾਬੀ', flag:'🇨🇦',
  tagline:'ਕਾਰੋਬਾਰੀ ਵਿਕਾਸ ਲਈ ਤੁਹਾਡੀ AI ਕਾਰਜ ਸ਼ਕਤੀ™',
  live:'ਲਾਈਵ', reconnecting:'ਮੁੜ ਜੁੜ ਰਿਹਾ ਹੈ…',
  tabs:{ home:'🏠 ਹੋਮ', dashboard:'📊 ਡੈਸ਼ਬੋਰਡ', callCenter:'🎧 ਕਾਲ ਸੈਂਟਰ', businesses:'🏢 CRM ਅਤੇ ਵਿਕਰੀ', appointments:'📅 ਅਪੌਇੰਟਮੈਂਟ', ai:'🤖 AI ਵਿਸ਼ਲੇਸ਼ਕ' },
  home:{ book:'ਅਪੌਇੰਟਮੈਂਟ ਬੁੱਕ ਕਰੋ', viewDash:'ਡੈਸ਼ਬੋਰਡ ਵੇਖੋ', heroTag:'— ਕਾਰੋਬਾਰੀ ਵਿਕਾਸ ਲਈ ਤੁਹਾਡੀ AI ਕਾਰਜ ਸ਼ਕਤੀ™ —', comingSoon:'ਜਲਦ ਆ ਰਿਹਾ ਹੈ', comingSoonSub:'ਇਹ ਮੌਡਿਊਲ ਵਿਕਾਸ ਅਧੀਨ ਹੈ।', back:'← ਹੋਮ ਤੇ ਵਾਪਸ' },
  trust:['ਆਲ-ਇਨ-ਵਨ ਪਲੇਟਫਾਰਮ','AI ਸੰਚਾਲਿਤ','ਮਨੁੱਖ ਪ੍ਰਵਾਨਿਤ','ਨਤੀਜਾ ਕੇਂਦਰਿਤ','ਸੁਰੱਖਿਅਤ ਅਤੇ ਭਰੋਸੇਯੋਗ'],
  c:{ save:'ਸੇਵ ਕਰੋ', cancel:'ਰੱਦ ਕਰੋ', edit:'ਸੋਧੋ', delete:'ਮਿਟਾਓ', add:'ਜੋੜੋ', new:'ਨਵਾਂ', search:'ਖੋਜੋ…', loading:'ਲੋਡ ਹੋ ਰਿਹਾ ਹੈ…', back:'ਵਾਪਸ', name:'ਨਾਮ', email:'ਈਮੇਲ', phone:'ਫ਼ੋਨ', notes:'ਨੋਟਸ', status:'ਸਥਿਤੀ', date:'ਮਿਤੀ', time:'ਸਮਾਂ', actions:'ਕਾਰਵਾਈਆਂ', noData:'ਕੋਈ ਡੇਟਾ ਨਹੀਂ।', all:'ਸਭ', confirm:'ਪੁਸ਼ਟੀ ਕਰੋ', complete:'ਪੂਰਾ ਕਰੋ', selectBiz:'ਕਾਰੋਬਾਰ ਚੁਣੋ…' },
  call:{ newCall:'ਨਵੀਂ ਕਾਲ', dial:'📞 ਡਾਇਲ ਕਰੋ', end:'⏹ ਕਾਲ ਖਤਮ ਕਰੋ', answer:'📞 ਚੁੱਕੋ', decline:'📵 ਰੱਦ ਕਰੋ', micOn:'🎙 ਮਾਈਕ ਚਾਲੂ', micOff:'🎙 ਮਾਈਕ ਬੰਦ', live:'ਲਾਈਵ ਕਾਲ', transcript:'ਲਾਈਵ ਟ੍ਰਾਂਸਕ੍ਰਿਪਟ', aiAssist:'AI ਸਹਾਇਤਾ', ringing:'ਰਿੰਗ ਹੋ ਰਹੀ ਹੈ…', connecting:'ਜੁੜ ਰਿਹਾ ਹੈ…', callerName:'ਕਾਲਰ ਦਾ ਨਾਮ', reason:'ਕਾਲ ਦਾ ਕਾਰਨ', today:'ਅੱਜ ਦੀਆਂ ਕਾਲਾਂ', total:'ਕੁੱਲ ਦਰਜ', urgent:'ਜ਼ਰੂਰੀ', ready:'⬤ ਤਿਆਰ', noHistory:'ਕੋਈ ਕਾਲ ਇਤਿਹਾਸ ਨਹੀਂ।', duration:'ਮਿਆਦ', triage:'ਟ੍ਰਾਈਏਜ', sentiment:'ਭਾਵਨਾ', analyzing:'⏳ AI ਵਿਸ਼ਲੇਸ਼ਣ…', analysisReady:'✅ ਵਿਸ਼ਲੇਸ਼ਣ ਤਿਆਰ', typeHint:'AI ਚਾਲੂ ਕਰਨ ਲਈ 30+ ਅੱਖਰ ਟਾਈਪ ਕਰੋ' },
  biz:{ title:'ਕਾਰੋਬਾਰ / CRM', addNew:'+ ਕਾਰੋਬਾਰ ਜੋੜੋ', bizName:'ਕਾਰੋਬਾਰ ਦਾ ਨਾਮ', industry:'ਉਦਯੋਗ', revenue:'ਆਮਦਨ ($)', employees:'ਕਰਮਚਾਰੀ', noData:'ਕੋਈ ਕਾਰੋਬਾਰ ਨਹੀਂ। ਪਹਿਲਾ ਜੋੜੋ!' },
  appt:{ title:'ਅਪੌਇੰਟਮੈਂਟ', addNew:'+ ਨਵੀਂ ਅਪੌਇੰਟਮੈਂਟ', business:'ਕਾਰੋਬਾਰ', service:'ਸੇਵਾ', custName:'ਗਾਹਕ ਦਾ ਨਾਮ', custPhone:'ਗਾਹਕ ਦਾ ਫ਼ੋਨ', scheduled:'ਨਿਰਧਾਰਤ', confirmed:'ਪੁਸ਼ਟੀ ਹੋਈ', completed:'ਪੂਰੀ ਹੋਈ', noData:'ਕੋਈ ਅਪੌਇੰਟਮੈਂਟ ਨਹੀਂ।', quickAdd:'+ ਜਲਦੀ ਕਾਰੋਬਾਰ ਜੋੜੋ' },
  ai:{ title:'AI ਟ੍ਰਾਂਸਕ੍ਰਿਪਟ ਵਿਸ਼ਲੇਸ਼ਕ', placeholder:'ਇੱਥੇ ਟ੍ਰਾਂਸਕ੍ਰਿਪਟ ਪੇਸਟ ਕਰੋ…', analyze:'🧠 ਵਿਸ਼ਲੇਸ਼ਣ ਕਰੋ', analyzing:'⏳ ਵਿਸ਼ਲੇਸ਼ਣ ਹੋ ਰਿਹਾ ਹੈ…', summary:'ਸਾਰ', actionItems:'ਕਾਰਵਾਈ', noResult:'ਟ੍ਰਾਂਸਕ੍ਰਿਪਟ ਪੇਸਟ ਕਰੋ ਅਤੇ ਵਿਸ਼ਲੇਸ਼ਣ ਤੇ ਕਲਿੱਕ ਕਰੋ।' },
  dash:{ title:'ਡੈਸ਼ਬੋਰਡ', businesses:'ਕਾਰੋਬਾਰ', appointments:'ਅਪੌਇੰਟਮੈਂਟ', calls:'ਅੱਜ ਦੀਆਂ ਕਾਲਾਂ' },
})

// ── Italian ───────────────────────────────────────────────────────────────────
const IT = m(EN, {
  rtl:false, langName:'Italiano', flag:'🇮🇹',
  tagline:"La Tua Forza Lavoro AI per la Crescita Aziendale™",
  live:'In Diretta', reconnecting:'Riconnessione…',
  tabs:{ home:'🏠 Home', dashboard:'📊 Dashboard', callCenter:'🎧 Call Center', businesses:'🏢 CRM e Vendite', appointments:'📅 Appuntamenti', ai:'🤖 Analizzatore AI' },
  home:{ book:'Prenota Appuntamento', viewDash:'Visualizza Dashboard', heroTag:'— LA TUA FORZA LAVORO AI PER LA CRESCITA™ —', comingSoon:'Prossimamente', comingSoonSub:'Questo modulo è in fase di sviluppo e sarà disponibile nella prossima versione.', back:'← Torna alla Home' },
  trust:['PIATTAFORMA TUTTO-IN-UNO','ALIMENTATO DA AI','APPROVATO DAGLI UMANI','ORIENTATO AI RISULTATI','SICURO E AFFIDABILE'],
  c:{ save:'Salva', cancel:'Annulla', edit:'Modifica', delete:'Elimina', add:'Aggiungi', new:'Nuovo', search:'Cerca…', loading:'Caricamento…', back:'Indietro', name:'Nome', email:'Email', phone:'Telefono', notes:'Note', status:'Stato', date:'Data', time:'Ora', actions:'Azioni', noData:'Nessun dato.', all:'Tutti', confirm:'Conferma', complete:'Completa', selectBiz:'Seleziona azienda…' },
  call:{ newCall:'Nuova Chiamata', dial:'📞 Chiama', end:'⏹ Termina Chiamata', answer:'📞 Rispondi', decline:'📵 Rifiuta', micOn:'🎙 Mic Attivo', micOff:'🎙 Mic Disattivo', live:'CHIAMATA LIVE', transcript:'Trascrizione Live', aiAssist:'Assistente AI', ringing:'In chiamata…', connecting:'Connessione…', callerName:'Nome Chiamante', reason:'Motivo della Chiamata', today:'Chiamate Oggi', total:'Totale Registrate', urgent:'Urgente', ready:'⬤ Pronto', noHistory:'Nessuna cronologia chiamate.', duration:'Durata', triage:'Triage', sentiment:'Sentiment', analyzing:'⏳ AI sta analizzando…', analysisReady:'✅ Analisi pronta', typeHint:'Digita 30+ caratteri per attivare AI' },
  biz:{ title:'Aziende / CRM', addNew:'+ Aggiungi Azienda', bizName:"Nome dell'Azienda", industry:'Settore', revenue:'Fatturato ($)', employees:'Dipendenti', noData:'Nessuna azienda. Aggiungi la prima!' },
  appt:{ title:'Appuntamenti', addNew:'+ Nuovo Appuntamento', business:'Azienda', service:'Servizio', custName:'Nome Cliente', custPhone:'Telefono Cliente', scheduled:'Programmato', confirmed:'Confermato', completed:'Completato', noData:'Nessun appuntamento.', quickAdd:'+ Aggiungi Azienda Veloce' },
  ai:{ title:'Analizzatore Trascrizioni AI', placeholder:'Incolla la trascrizione qui…', analyze:'🧠 Analizza', analyzing:'⏳ Analisi in corso…', summary:'Riepilogo', actionItems:'Azioni', noResult:'Incolla una trascrizione e clicca Analizza.' },
  dash:{ title:'Dashboard', businesses:'Aziende', appointments:'Appuntamenti', calls:'Chiamate Oggi' },
})

// ── German ────────────────────────────────────────────────────────────────────
const DE = m(EN, {
  rtl:false, langName:'Deutsch', flag:'🇩🇪',
  tagline:'Ihre KI-Belegschaft für Unternehmenswachstum™',
  live:'Live', reconnecting:'Verbinde erneut…',
  tabs:{ home:'🏠 Startseite', dashboard:'📊 Dashboard', callCenter:'🎧 Callcenter', businesses:'🏢 CRM & Vertrieb', appointments:'📅 Termine', ai:'🤖 KI-Analysator' },
  home:{ book:'Termin buchen', viewDash:'Dashboard anzeigen', heroTag:'— IHRE KI-BELEGSCHAFT FÜR UNTERNEHMENSWACHSTUM™ —', comingSoon:'Demnächst', comingSoonSub:'Dieses Modul befindet sich in der Entwicklung und wird in der nächsten Version verfügbar sein.', back:'← Zurück zur Startseite' },
  trust:['ALL-IN-ONE-PLATTFORM','KI-GESTÜTZT','MENSCHLICH GEPRÜFT','ERGEBNISORIENTIERT','SICHER UND ZUVERLÄSSIG'],
  c:{ save:'Speichern', cancel:'Abbrechen', edit:'Bearbeiten', delete:'Löschen', add:'Hinzufügen', new:'Neu', search:'Suchen…', loading:'Laden…', back:'Zurück', name:'Name', email:'E-Mail', phone:'Telefon', notes:'Notizen', status:'Status', date:'Datum', time:'Uhrzeit', actions:'Aktionen', noData:'Keine Daten.', all:'Alle', confirm:'Bestätigen', complete:'Abschließen', selectBiz:'Unternehmen auswählen…' },
  call:{ newCall:'Neuer Anruf', dial:'📞 Wählen', end:'⏹ Anruf beenden', answer:'📞 Annehmen', decline:'📵 Ablehnen', micOn:'🎙 Mikrofon an', micOff:'🎙 Mikrofon aus', live:'LIVE-GESPRÄCH', transcript:'Live-Transkript', aiAssist:'KI-Hilfe', ringing:'Klingelt…', connecting:'Verbinde…', callerName:'Name des Anrufers', reason:'Anrufgrund', today:'Anrufe heute', total:'Gesamt erfasst', urgent:'Dringend', ready:'⬤ Bereit', noHistory:'Kein Anrufverlauf.', duration:'Dauer', triage:'Triage', sentiment:'Stimmung', analyzing:'⏳ KI analysiert…', analysisReady:'✅ Analyse bereit', typeHint:'30+ Zeichen eingeben, um KI zu aktivieren' },
  biz:{ title:'Unternehmen / CRM', addNew:'+ Unternehmen hinzufügen', bizName:'Unternehmensname', industry:'Branche', revenue:'Umsatz ($)', employees:'Mitarbeiter', noData:'Keine Unternehmen. Erstes hinzufügen!' },
  appt:{ title:'Termine', addNew:'+ Neuer Termin', business:'Unternehmen', service:'Dienst', custName:'Kundenname', custPhone:'Kundentelefon', scheduled:'Geplant', confirmed:'Bestätigt', completed:'Abgeschlossen', noData:'Keine Termine.', quickAdd:'+ Schnell Unternehmen hinzufügen' },
  ai:{ title:'KI-Transkriptanalysator', placeholder:'Transkript hier einfügen…', analyze:'🧠 Analysieren', analyzing:'⏳ Analysiere…', summary:'Zusammenfassung', actionItems:'Aufgaben', noResult:'Transkript einfügen und Analysieren klicken.' },
  dash:{ title:'Dashboard', businesses:'Unternehmen', appointments:'Termine', calls:'Anrufe heute' },
})

// ── Japanese ──────────────────────────────────────────────────────────────────
const JA = m(EN, {
  rtl:false, langName:'日本語', flag:'🇯🇵',
  tagline:'ビジネス成長のためのAI人材™',
  live:'ライブ', reconnecting:'再接続中…',
  tabs:{ home:'🏠 ホーム', dashboard:'📊 ダッシュボード', callCenter:'🎧 コールセンター', businesses:'🏢 CRM・営業', appointments:'📅 予約', ai:'🤖 AI分析' },
  home:{ book:'予約する', viewDash:'ダッシュボードを見る', heroTag:'— ビジネス成長のためのAI人材™ —', comingSoon:'近日公開', comingSoonSub:'このモジュールは開発中で、次のリリースで利用可能になります。', back:'← ホームに戻る' },
  trust:['オールインワンプラットフォーム','AI搭載','人間が承認','結果重視','安全・信頼'],
  c:{ save:'保存', cancel:'キャンセル', edit:'編集', delete:'削除', add:'追加', new:'新規', search:'検索…', loading:'読み込み中…', back:'戻る', name:'名前', email:'メール', phone:'電話', notes:'メモ', status:'ステータス', date:'日付', time:'時間', actions:'操作', noData:'データなし。', all:'すべて', confirm:'確認', complete:'完了', selectBiz:'企業を選択…' },
  call:{ newCall:'新規通話', dial:'📞 発信', end:'⏹ 通話終了', answer:'📞 応答', decline:'📵 拒否', micOn:'🎙 マイクON', micOff:'🎙 マイクOFF', live:'ライブ通話', transcript:'ライブ文字起こし', aiAssist:'AIアシスト', ringing:'呼び出し中…', connecting:'接続中…', callerName:'発信者名', reason:'通話理由', today:'本日の通話', total:'合計記録', urgent:'緊急', ready:'⬤ 準備完了', noHistory:'通話履歴なし。', duration:'通話時間', triage:'トリアージ', sentiment:'感情', analyzing:'⏳ AI分析中…', analysisReady:'✅ 分析完了', typeHint:'30文字以上入力してAIを起動' },
  biz:{ title:'企業 / CRM', addNew:'+ 企業を追加', bizName:'企業名', industry:'業種', revenue:'収益 ($)', employees:'従業員数', noData:'企業なし。最初を追加してください！' },
  appt:{ title:'予約', addNew:'+ 新規予約', business:'企業', service:'サービス', custName:'顧客名', custPhone:'顧客電話', scheduled:'予約済み', confirmed:'確認済み', completed:'完了', noData:'予約なし。', quickAdd:'+ 企業を素早く追加' },
  ai:{ title:'AI文字起こし分析', placeholder:'通話の文字起こしをここに貼り付け…', analyze:'🧠 分析', analyzing:'⏳ 分析中…', summary:'要約', actionItems:'アクション項目', noResult:'文字起こしを貼り付けて分析をクリック。' },
  dash:{ title:'ダッシュボード', businesses:'企業', appointments:'予約', calls:'本日の通話' },
})

// ── Gujarati ──────────────────────────────────────────────────────────────────
const GU = m(EN, {
  rtl:false, langName:'ગુજરાતી', flag:'🇮🇳',
  tagline:'વ્યવસાય વૃદ્ધિ માટે તમારી AI કાર્યબળ™',
  live:'લાઈવ', reconnecting:'ફરી જોડાઈ રહ્યું છે…',
  tabs:{ home:'🏠 હોમ', dashboard:'📊 ડૅશબોર્ડ', callCenter:'🎧 કૉલ સેન્ટર', businesses:'🏢 CRM અને સેલ્સ', appointments:'📅 એપોઇન્ટમેન્ટ', ai:'🤖 AI વિશ્લેષક' },
  home:{ book:'એપોઇન્ટમેન્ટ બુક કરો', viewDash:'ડૅશબોર્ડ જુઓ', heroTag:'— વ્યવસાય વૃદ્ધિ માટે તમારી AI કાર્યબળ™ —', comingSoon:'ટૂંક સમયમાં', comingSoonSub:'આ મોડ્યુલ વિકાસ હેઠળ છે અને આગળના રિલીઝ માં ઉપલબ્ધ થશે.', back:'← હોમ પર પાછા' },
  trust:['ઑલ-ઇન-વન પ્લૅટફૉર્મ','AI સંચાલિત','માનવ-મંજૂર','પરિણામ-કેન્દ્રિત','સુરક્ષિત અને વિશ્વસનીય'],
  c:{ save:'સ્ટોર કરો', cancel:'રદ કરો', edit:'ફેરફાર કરો', delete:'ભૂંસો', add:'ઉમેરો', new:'નવો', search:'શોધો…', loading:'લોડ થઈ રહ્યું છે…', back:'પાછળ', name:'નામ', email:'ઈ-મેઈલ', phone:'ફોન', notes:'નોટ્સ', status:'સ્ટૅટસ', date:'તારીખ', time:'સમય', actions:'ક્રિયા', noData:'કોઈ ડૅટા નથી.', all:'બધા', confirm:'પુષ્ટિ કરો', complete:'પૂર્ણ કરો', selectBiz:'વ્યવસાય પ્રિ કરો…' },
  call:{ newCall:'નવો કૉલ', dial:'📞 ડાયલ કરો', end:'⏹ કૉલ સમાપ્ત', answer:'📞 ઉઠાવો', decline:'📵 નકારો', micOn:'🎙 માઇક ચાલુ', micOff:'🎙 માઇક બંધ', live:'લાઈવ કૉલ', transcript:'લાઈવ ટ્રાન્સ', aiAssist:'AI સહાય', ringing:'રિંગ થઈ રહ્યો છે…', connecting:'જોડાઈ રહ્યો છે…', callerName:'કૉલ કરનારનું નામ', reason:'કૉલનું કારણ', today:'આજના કૉલ', total:'કુલ નોંધ', urgent:'અત્યંત ઝડપી', ready:'⬤ તૈયાર', noHistory:'કૉલ ઇતિહાસ નથી.', duration:'અવધિ', triage:'ટ્રાઈઝ', sentiment:'ભાવના', analyzing:'⏳ AI વિશ્લેષણ…', analysisReady:'✅ વિશ્લેષણ તૈયાર', typeHint:'AI ચાલુ કરવા 30+ અક્ષર ટાઈપ કરો' },
  biz:{ title:'વ્યવસાય / CRM', addNew:'+ વ્યવસાય ઉમેરો', bizName:'વ્યવસાયનું નામ', industry:'ઉદ્યોગ', revenue:'આવક ($)', employees:'કર્મચારીઓ', noData:'કોઈ વ્યવસાય નથી. પ્રથમ ઉમેરો!' },
  appt:{ title:'એપોઇન્ટમેન્ટ', addNew:'+ નવી એપોઇન્ટ', business:'વ્યવસાય', service:'સેવા', custName:'ગ્રાહકનું નામ', custPhone:'ગ્રાહકનો ફોન', scheduled:'નિર્ધારિત', confirmed:'પુષ્ટિ થઈ', completed:'પૂર્ણ', noData:'કોઈ એપોઇ. નથી.', quickAdd:'+ ઝડપી વ્યવસાય ઉમેરો' },
  ai:{ title:'AI ટ્રાન્સ. વિશ્લેષક', placeholder:'અહીં ટ્રાન્સ. પેસ્ટ કરો…', analyze:'🧠 વિશ્લેષণ', analyzing:'⏳ વિશ્લેષણ…', summary:'સારાંશ', actionItems:'ક્રિયા', noResult:'ટ્રાન્સ. પેસ્ટ કરો અને ક્લિક કરો.' },
  dash:{ title:'ડૅશબોર્ડ', businesses:'વ્યવસાય', appointments:'એપોઇ.', calls:'આજના કૉલ' },
})

// ── Bengali ───────────────────────────────────────────────────────────────────
const BN = m(EN, {
  rtl:false, langName:'বাংলা', flag:'🇧🇩',
  tagline:'ব্যবসায়িক প্রবৃদ্ধির জন্য আপনার AI কর্মশক্তি™',
  live:'লাইভ', reconnecting:'পুনরায় সংযুক্ত হচ্ছে…',
  tabs:{ home:'🏠 হোম', dashboard:'📊 ড্যাশবোর্ড', callCenter:'🎧 কল সেন্টার', businesses:'🏢 CRM ও বিক্রয়', appointments:'📅 অ্যাপয়েন্টমেন্ট', ai:'🤖 AI বিশ্লেষক' },
  home:{ book:'অ্যাপয়েন্টমেন্ট বুক করুন', viewDash:'ড্যাশবোর্ড দেখুন', heroTag:'— ব্যবসায়িক প্রবৃদ্ধির জন্য আপনার AI কর্মশক্তি™ —', comingSoon:'শীঘ্রই আসছে', comingSoonSub:'এই মডিউলটি উন্নয়নাধীন এবং পরবর্তী রিলিজে পাওয়া যাবে।', back:'← হোমে ফিরুন' },
  trust:['অল-ইন-ওয়ান প্ল্যাটফর্ম','AI চালিত','মানব অনুমোদিত','ফলাফলমুখী','নিরাপদ ও নির্ভরযোগ্য'],
  c:{ save:'সংরক্ষণ', cancel:'বাতিল', edit:'সম্পাদনা', delete:'মুছুন', add:'যোগ করুন', new:'নতুন', search:'অনুসন্ধান…', loading:'লোড হচ্ছে…', back:'ফিরে যান', name:'নাম', email:'ইমেইল', phone:'ফোন', notes:'নোটস', status:'স্ট্যাটাস', date:'তারিখ', time:'সময়', actions:'কার্যক্রম', noData:'কোন ডেটা নেই।', all:'সব', confirm:'নিশ্চিত করুন', complete:'সম্পূর্ণ করুন', selectBiz:'ব্যবসা বেছে নিন…' },
  call:{ newCall:'নতুন কল', dial:'📞 ডায়াল করুন', end:'⏹ কল শেষ করুন', answer:'📞 ধরুন', decline:'📵 প্রত্যাখ্যান', micOn:'🎙 মাইক চালু', micOff:'🎙 মাইক বন্ধ', live:'লাইভ কল', transcript:'লাইভ ট্রান্সক্রিপ্ট', aiAssist:'AI সহায়তা', ringing:'রিং হচ্ছে…', connecting:'সংযুক্ত হচ্ছে…', callerName:'কলারের নাম', reason:'কলের কারণ', today:'আজকের কল', total:'মোট নথিভুক্ত', urgent:'জরুরি', ready:'⬤ প্রস্তুত', noHistory:'কোন কল ইতিহাস নেই।', duration:'সময়কাল', triage:'ট্রাইয়াজ', sentiment:'অনুভূতি', analyzing:'⏳ AI বিশ্লেষণ…', analysisReady:'✅ বিশ্লেষণ প্রস্তুত', typeHint:'AI সক্রিয় করতে ৩০+ অক্ষর টাইপ করুন' },
  biz:{ title:'ব্যবসা / CRM', addNew:'+ ব্যবসা যোগ করুন', bizName:'ব্যবসার নাম', industry:'শিল্প', revenue:'রাজস্ব ($)', employees:'কর্মচারী', noData:'কোন ব্যবসা নেই। প্রথমটি যোগ করুন!' },
  appt:{ title:'অ্যাপয়েন্টমেন্ট', addNew:'+ নতুন অ্যাপয়েন্টমেন্ট', business:'ব্যবসা', service:'সেবা', custName:'গ্রাহকের নাম', custPhone:'গ্রাহকের ফোন', scheduled:'নির্ধারিত', confirmed:'নিশ্চিত', completed:'সম্পূর্ণ', noData:'কোন অ্যাপয়েন্টমেন্ট নেই।', quickAdd:'+ দ্রুত ব্যবসা যোগ করুন' },
  ai:{ title:'AI ট্রান্সক্রিপ্ট বিশ্লেষক', placeholder:'এখানে ট্রান্সক্রিপ্ট পেস্ট করুন…', analyze:'🧠 বিশ্লেষণ করুন', analyzing:'⏳ বিশ্লেষণ হচ্ছে…', summary:'সারসংক্ষেপ', actionItems:'কার্যক্রম', noResult:'ট্রান্সক্রিপ্ট পেস্ট করুন এবং বিশ্লেষণ ক্লিক করুন।' },
  dash:{ title:'ড্যাশবোর্ড', businesses:'ব্যবসা', appointments:'অ্যাপয়েন্টমেন্ট', calls:'আজকের কল' },
})

// ── Language registry ─────────────────────────────────────────────────────────
export const LANGS = { en:EN, es:ES, ur:UR, vi:VI, fr:FR, zh:ZH, tl:TL, ko:KO, ar:AR, hi:HI, pt:PT, ru:RU, ht:HT, pl:PL, pa:PA, it:IT, de:DE, ja:JA, gu:GU, bn:BN }

export const LANG_LIST = [
  { code:'en', name:'English',         flag:'🇺🇸' },
  { code:'es', name:'Español',         flag:'🇲🇽' },
  { code:'ur', name:'اردو',            flag:'🇵🇰' },
  { code:'vi', name:'Tiếng Việt',      flag:'🇻🇳' },
  { code:'fr', name:'Français',        flag:'🇫🇷' },
  { code:'zh', name:'中文',             flag:'🇨🇳' },
  { code:'tl', name:'Filipino',        flag:'🇵🇭' },
  { code:'ko', name:'한국어',           flag:'🇰🇷' },
  { code:'ar', name:'العربية',         flag:'🇸🇦' },
  { code:'hi', name:'हिन्दी',          flag:'🇮🇳' },
  { code:'pt', name:'Português',       flag:'🇧🇷' },
  { code:'ru', name:'Русский',         flag:'🇷🇺' },
  { code:'ht', name:'Kreyòl Ayisyen',  flag:'🇭🇹' },
  { code:'pl', name:'Polski',          flag:'🇵🇱' },
  { code:'pa', name:'ਪੰਜਾਬੀ',         flag:'🇨🇦' },
  { code:'it', name:'Italiano',        flag:'🇮🇹' },
  { code:'de', name:'Deutsch',         flag:'🇩🇪' },
  { code:'ja', name:'日本語',           flag:'🇯🇵' },
  { code:'gu', name:'ગુજરાતી',        flag:'🇮🇳' },
  { code:'bn', name:'বাংলা',           flag:'🇧🇩' },
]

// ── Context & hook ─────────────────────────────────────────────────────────────
const LangCtx = createContext({ lang:'en', t: LANGS.en, setLang:()=>{} })

export function LangProvider({ children }) {
  const [lang, setLangState] = useState(() => localStorage.getItem('ez_nexus_lang') || 'en')

  const setLang = (code) => {
    localStorage.setItem('ez_nexus_lang', code)
    setLangState(code)
    document.documentElement.dir = LANGS[code]?.rtl ? 'rtl' : 'ltr'
    document.documentElement.lang = code
  }

  // Apply dir on mount
  React.useEffect(() => {
    document.documentElement.dir = LANGS[lang]?.rtl ? 'rtl' : 'ltr'
    document.documentElement.lang = lang
  }, [lang])

  const t = LANGS[lang] || LANGS.en
  return <LangCtx.Provider value={{ lang, t, setLang }}>{children}</LangCtx.Provider>
}

export function useLang() { return useContext(LangCtx) }
