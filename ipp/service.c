#define _GNU_SOURCE
#include <pappl/pappl.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/wait.h>
#include <signal.h>
#include <time.h>
#include <errno.h>
#include <sys/prctl.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <stdatomic.h>

static char recovery_path[1024], refresh_path[1024];
static _Atomic unsigned long long latest_observation;

typedef struct { FILE *file; unsigned rows, pages, confirmed; bool failed; unsigned reason; char status_message[512]; char dir[256]; } job_data;
/* PAPPL 1.4 counts raster ingestion; physical progress belongs to our worker. */
static void set_confirmed(pappl_job_t *job, unsigned count) {
 papplJobSetImpressionsCompleted(job,(int)count-papplJobGetImpressionsCompleted(job));
}
#define OUR_REASONS (PAPPL_PREASON_COVER_OPEN|PAPPL_PREASON_MEDIA_EMPTY|PAPPL_PREASON_MEDIA_NEEDED|PAPPL_PREASON_OFFLINE|PAPPL_PREASON_OTHER)
static pappl_preason_t reason_flag(unsigned reason) {
 switch(reason){
  case 1:return PAPPL_PREASON_COVER_OPEN;
  case 2:return PAPPL_PREASON_MEDIA_NEEDED;
  case 3:case 6:case 7:return PAPPL_PREASON_OTHER;
  case 4:case 5:return PAPPL_PREASON_OFFLINE;
  default:return PAPPL_PREASON_NONE;
 }
}
/* This callback reads a user-requested snapshot; it never opens Bluetooth. */
static bool cached_status(pappl_printer_t *printer) {
 if(access(recovery_path,F_OK)==0){papplPrinterSetReasons(printer,PAPPL_PREASON_OTHER,OUR_REASONS);return true;}
 FILE *file=fopen(refresh_path,"r");if(!file)return true;
 unsigned version,reason;unsigned long long observed;
 bool valid=fscanf(file,"%u %llu %u",&version,&observed,&reason)==3;
 fclose(file);
 if(!valid || version!=1 || reason>8 || observed<=atomic_load(&latest_observation))return true;
 papplPrinterSetReasons(printer,reason_flag(reason),OUR_REASONS);
 atomic_store(&latest_observation,observed);
 papplSystemAddEvent(papplPrinterGetSystem(printer),printer,NULL,PAPPL_EVENT_PRINTER_STATE_CHANGED,NULL);
 return true;
}
static void update_status(pappl_job_t *job, job_data *s) {
 char path[300],message[512];unsigned version,count,reason;
 snprintf(path,sizeof(path),"%s/status.txt",s->dir);
 FILE *f=fopen(path,"r");if(!f)return;
 bool valid=fscanf(f,"%u %u %u\n",&version,&count,&reason)==3 && fgets(message,sizeof(message),f);
 fclose(f);
 if(!valid || version!=1 || count<s->confirmed || count>s->pages || reason>8)return;
 message[strcspn(message,"\r\n")]=0;
 bool changed=s->confirmed!=count || s->reason!=reason || strcmp(s->status_message,message);
 s->confirmed=count;s->reason=reason;snprintf(s->status_message,sizeof(s->status_message),"%s",message);set_confirmed(job,count);
 papplPrinterSetReasons(papplJobGetPrinter(job),reason_flag(reason),OUR_REASONS);
 if(changed){struct timespec observed;clock_gettime(CLOCK_REALTIME,&observed);atomic_store(&latest_observation,(unsigned long long)observed.tv_sec*1000000000ULL+observed.tv_nsec);}
 papplJobSetMessage(job,"%s",message);
 if(changed){pappl_printer_t *printer=papplJobGetPrinter(job);papplSystemAddEvent(papplPrinterGetSystem(printer),printer,job,PAPPL_EVENT_JOB_PROGRESS|PAPPL_EVENT_PRINTER_STATE_CHANGED,NULL);}
}
static bool start_job(pappl_job_t *j, pappl_pr_options_t *o, pappl_device_t *d) {
 (void)o;(void)d;
 set_confirmed(j,0);
 papplJobSetMessage(j,"Preparing raster; no labels confirmed.");
 if(access(recovery_path,F_OK)==0){papplPrinterSetReasons(papplJobGetPrinter(j),PAPPL_PREASON_OTHER,OUR_REASONS);papplJobSetMessage(j,"Service previously exited unexpectedly; cancel old CUPS jobs and explicitly clear the recovery hold.");return false;}
 job_data *s=calloc(1,sizeof(*s)); if(!s)return false;
 snprintf(s->dir,sizeof(s->dir),"/tmp/niimbot-job-XXXXXX");
 if(!mkdtemp(s->dir)){free(s);return false;}
 papplJobSetData(j,s);return true;
}
static bool start_page(pappl_job_t *j,pappl_pr_options_t *o,pappl_device_t *d,unsigned page) {
 (void)d;(void)page;job_data *s=papplJobGetData(j);
 set_confirmed(j,0);
 if((o->header.cupsWidth<95 || o->header.cupsWidth>96) || (o->header.cupsHeight<319 || o->header.cupsHeight>320) || o->header.cupsBitsPerPixel!=1 || ++s->pages>100){s->failed=true;return false;}
 char name[300];snprintf(name,sizeof(name),"%s/%u.raw",s->dir,s->pages);
 s->file=fopen(name,"wb");s->rows=0;if(!s->file)s->failed=true;return s->file!=NULL;
}
static bool line(pappl_job_t *j,pappl_pr_options_t *o,pappl_device_t *d,unsigned y,const unsigned char *pixels) {
 (void)o;(void)d;job_data *s=papplJobGetData(j);
 if(papplJobIsCanceled(j)||!s->file||y!=s->rows){s->failed=true;return false;}
 unsigned char row[96];for(unsigned x=0;x<96;x++)row[x]=x>=o->header.cupsWidth?255:(pixels[x/8]&(128>>(x%8)))?0:255;
 if(fwrite(row,1,96,s->file)!=96){s->failed=true;return false;}s->rows++;return true;
}
static bool end_page(pappl_job_t *j,pappl_pr_options_t *o,pappl_device_t *d,unsigned page) {
 (void)o;(void)d;(void)page;job_data *s=papplJobGetData(j);
 if(s->file && s->rows==319){unsigned char white[96];memset(white,255,96);if(fwrite(white,1,96,s->file)==96)s->rows++;}
 bool ok=s->file && s->rows==320;
 if(s->file){if(fclose(s->file))ok=false;s->file=NULL;}s->failed|=!ok;return ok;
}
static bool end_job(pappl_job_t *j,pappl_pr_options_t *o,pappl_device_t *d) {
 (void)o;(void)d;job_data *s=papplJobGetData(j);
 if(!s)return false;
 set_confirmed(j,0);
 papplJobSetImpressions(j,(int)s->pages);
 papplJobSetCopiesCompleted(j,-papplJobGetCopiesCompleted(j));
 bool ok=false;
 if(!s->failed && !papplJobIsCanceled(j) && papplJobGetState(j)==IPP_JSTATE_PROCESSING) {
  char copies[16];snprintf(copies,sizeof(copies),"1"); /* PAPPL images/CUPS raster already expand copies. */
  pid_t parent=getpid();
  pid_t pid=fork();
  if(pid==0){
   if(prctl(PR_SET_PDEATHSIG,SIGTERM)<0 || getppid()!=parent)_exit(127);
   execlp("python3","python3","ipp/supervise.py",s->dir,copies,(char*)NULL);_exit(127);
  }
  if(pid>0){
   int status=0;bool reaped=false,stopping=false;
   struct timespec now;clock_gettime(CLOCK_MONOTONIC,&now);
   time_t until=now.tv_sec+35+30*s->pages,stop_at=0;
   while(true){
    update_status(j,s);
    pid_t result=waitpid(pid,&status,WNOHANG);
    if(result==pid){reaped=true;break;}
    if(result<0){if(errno==EINTR)continue;break;}
    clock_gettime(CLOCK_MONOTONIC,&now);
    if(!stopping&&(papplJobIsCanceled(j)||now.tv_sec>=until)){
     kill(pid,SIGTERM);stopping=true;stop_at=now.tv_sec+5;
    }
    if(stopping&&now.tv_sec>=stop_at)kill(pid,SIGKILL);
    usleep(100000);
   }
   update_status(j,s);
   ok=reaped&&!stopping&&!papplJobIsCanceled(j)&&WIFEXITED(status)&&WEXITSTATUS(status)==0;
  }
 }
 if(ok){set_confirmed(j,s->pages);papplJobSetCopiesCompleted(j,papplJobGetCopies(j));}
 if(!ok){
 char error_path[300],message[512]="Job failed or cancelled; output may be partial. Check service log before explicitly resubmitting.";
 snprintf(error_path,sizeof(error_path),"%s/error.txt",s->dir);FILE *error=fopen(error_path,"r");if(error){if(!fgets(message,sizeof(message),error)){}fclose(error);unlink(error_path);}
 if(s->confirmed==0)papplJobSetMessage(j,"%s",message);
 update_status(j,s);
 papplJobSetReasons(j,PAPPL_JREASON_ERRORS_DETECTED,PAPPL_JREASON_NONE);
 }
 if(s){if(s->file)fclose(s->file);for(unsigned p=1;p<=s->pages;p++){char n[300];snprintf(n,sizeof(n),"%s/%u.raw",s->dir,p);unlink(n);}char n[300];snprintf(n,sizeof(n),"%s/manifest.json",s->dir);unlink(n);snprintf(n,sizeof(n),"%s/status.txt",s->dir);unlink(n);snprintf(n,sizeof(n),"%s/status.tmp",s->dir);unlink(n);rmdir(s->dir);free(s);papplJobSetData(j,NULL);}return ok;
}

static bool driver(pappl_system_t *sys,const char *name,const char *uri,const char *id,pappl_pr_driver_data_t *v,ipp_t **attrs,void *data) {
 (void)sys;(void)name;(void)uri;(void)id;(void)attrs;(void)data;
 snprintf(v->make_and_model,sizeof(v->make_and_model),"Niimbot D110M");
 v->status_cb=cached_status;
 v->rstartjob_cb=start_job;v->rstartpage_cb=start_page;v->rwriteline_cb=line;v->rendpage_cb=end_page;v->rendjob_cb=end_job;
 v->ppm=10;v->format="application/x-niimbot-disabled";
 v->num_resolution=1;v->x_resolution[0]=v->y_resolution[0]=v->x_default=v->y_default=203;
 v->raster_types=v->force_raster_type=PAPPL_PWG_RASTER_TYPE_BLACK_1;
 v->color_supported=PAPPL_COLOR_MODE_BI_LEVEL|PAPPL_COLOR_MODE_MONOCHROME;v->color_default=PAPPL_COLOR_MODE_MONOCHROME;
 v->sides_supported=v->sides_default=PAPPL_SIDES_ONE_SIDED;
 v->num_media=1;v->media[0]="custom_12x40mm_12x40mm";
 v->media_default.size_width=1200;v->media_default.size_length=4000;strcpy(v->media_default.size_name,v->media[0]);strcpy(v->media_default.source,"roll-1");strcpy(v->media_default.type,"labels");v->media_ready[0]=v->media_default;
 v->num_source=1;v->source[0]="roll-1";v->num_type=1;v->type[0]="labels";
 return true;
}
static bool device_open(pappl_device_t *d,const char *u,const char *n){(void)d;(void)u;(void)n;return true;}
static void device_close(pappl_device_t *d){(void)d;}
int main(void) {
 const char *state=getenv("XDG_STATE_HOME"),*home=getenv("HOME");
 int length=state ? snprintf(refresh_path,sizeof(refresh_path),"%s/niimbot/refresh-status.txt",state) : snprintf(refresh_path,sizeof(refresh_path),"%s/.local/state/niimbot/refresh-status.txt",home?home:"");
 if(length<0 || length>=(int)sizeof(refresh_path))return 1;
 pappl_pr_driver_t drivers[]={{"niimbot-d110m","Niimbot D110M 12x40 mm",NULL,NULL}};
 const char *spool=getenv("NIIMBOT_SPOOL");if(!spool){fprintf(stderr,"Set NIIMBOT_SPOOL to a private directory\n");return 1;}
 papplDeviceAddScheme("niimbot",PAPPL_DEVTYPE_CUSTOM_LOCAL,NULL,device_open,device_close,NULL,NULL,NULL,NULL);
 pappl_system_t *s=papplSystemCreate(PAPPL_SOPTIONS_NO_TLS,"Niimbot",getenv("NIIMBOT_PORT")?atoi(getenv("NIIMBOT_PORT")):8631,NULL,spool,"-",PAPPL_LOGLEVEL_DEBUG,NULL,false);
 if(!s)return 1;
 papplSystemSetHostName(s,"localhost");
 papplSystemSetPrinterDrivers(s,1,drivers,NULL,NULL,driver,NULL);
 if(!papplSystemAddListeners(s,"127.0.0.1"))return 1;
 pappl_printer_t *p=papplPrinterCreate(s,1,"Niimbot D110M", "niimbot-d110m",NULL,"niimbot://configured");
 if(!p)return 1;
 papplPrinterSetDNSSDName(p,NULL);papplSystemSetDNSSDName(s,NULL);
 char active_path[1024];
 if(snprintf(active_path,sizeof(active_path),"%s/service-active",spool)>=(int)sizeof(active_path) ||
    snprintf(recovery_path,sizeof(recovery_path),"%s/recovery-required",spool)>=(int)sizeof(recovery_path))return 1;
 int marker=open(active_path,O_WRONLY|O_CREAT|O_EXCL,0600);
 if(marker<0){
  if(errno!=EEXIST)return 1;
  int hold=open(recovery_path,O_WRONLY|O_CREAT,0600);if(hold<0)return 1;
  if(fsync(hold)<0){close(hold);return 1;}close(hold);
 }else{if(fsync(marker)<0){close(marker);return 1;}close(marker);}
 int directory=open(spool,O_DIRECTORY);if(directory<0)return 1;
 if(fsync(directory)<0){close(directory);return 1;}
 papplSystemRun(s);papplSystemDelete(s);
 unlink(active_path);fsync(directory);close(directory);return 0;
}
